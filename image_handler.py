"""
Image duplicate detection and blocking system with watermarking support
"""

import logging
import hashlib
import os
import tempfile
from typing import Optional, Dict, List, Any
from io import BytesIO
from datetime import datetime

from database import DatabaseManager, MessagePair
from config import Config

logger = logging.getLogger(__name__)

# Try to import image processing libraries
try:
    import imagehash
    from PIL import Image, ImageDraw, ImageFont
    IMAGE_PROCESSING_AVAILABLE = True
except ImportError:
    IMAGE_PROCESSING_AVAILABLE = False
    imagehash = None
    Image = None
    ImageDraw = None
    ImageFont = None
    logger.warning("Image processing libraries not available. Image blocking disabled.")

class ImageHandler:
    """Image duplicate detection and blocking system with watermarking support"""
    
    def __init__(self, db_manager: DatabaseManager, config: Config):
        self.db_manager = db_manager
        self.config = config
        self.enabled = IMAGE_PROCESSING_AVAILABLE
        
        # Hash cache to avoid recomputing
        self._hash_cache: Dict[int, str] = {}
        
    async def is_image_blocked(self, event, pair: MessagePair) -> bool:
        """Check if image should be blocked as duplicate"""
        if not self.enabled:
            return False
        
        try:
            # Process photo messages and documents that are images
            if not hasattr(event, 'media') or not event.media:
                return False
            
            from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
            
            # Check if it's a photo or image document
            is_image = False
            if isinstance(event.media, MessageMediaPhoto):
                is_image = True
            elif isinstance(event.media, MessageMediaDocument):
                document = getattr(event.media, 'document', None)
                if document and hasattr(document, 'mime_type'):
                    mime_type = getattr(document, 'mime_type', '').lower()
                    is_image = mime_type.startswith('image/')
            
            if not is_image:
                return False
            
            # Download and hash the image
            image_hash = await self._get_image_hash(event)
            if not image_hash:
                return False
            
            # Check against blocked images
            is_blocked = await self._check_blocked_images(image_hash, pair)
            
            if is_blocked:
                logger.debug(f"Image blocked as duplicate: {image_hash}")
                # Update usage count
                await self._update_image_usage(image_hash, pair)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error checking image block: {e}")
            return False
    
    async def add_image_block(self, event, pair: Optional[MessagePair] = None, 
                             description: str = "", 
                             blocked_by: str = "",
                             block_scope: str = "pair",
                             similarity_threshold: Optional[int] = None) -> bool:
        """Add image to block list"""
        if not self.enabled:
            return False
        
        try:
            image_hash = await self._get_image_hash(event)
            if not image_hash:
                return False
            
            # Use config default if threshold not specified
            if similarity_threshold is None:
                similarity_threshold = self.config.SIMILARITY_THRESHOLD
            
            # Save to database
            async with self.db_manager.get_connection() as conn:
                await conn.execute('''
                    INSERT OR REPLACE INTO blocked_images 
                    (phash, pair_id, description, blocked_by, block_scope, similarity_threshold)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    image_hash,
                    pair.id if (pair and block_scope == "pair") else None,
                    description,
                    blocked_by,
                    block_scope,
                    similarity_threshold
                ))
                await conn.commit()
            
            logger.info(f"Added image block: {image_hash} (scope: {block_scope})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add image block: {e}")
            return False
    
    async def remove_image_block(self, image_hash: str, pair_id: Optional[int] = None) -> bool:
        """Remove image from block list"""
        try:
            async with self.db_manager.get_connection() as conn:
                if pair_id:
                    await conn.execute(
                        'DELETE FROM blocked_images WHERE phash = ? AND pair_id = ?',
                        (image_hash, pair_id)
                    )
                else:
                    await conn.execute(
                        'DELETE FROM blocked_images WHERE phash = ?',
                        (image_hash,)
                    )
                await conn.commit()
            
            logger.info(f"Removed image block: {image_hash}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to remove image block: {e}")
            return False
    
    async def _get_image_hash(self, event) -> Optional[str]:
        """Get perceptual hash of image"""
        if not self.enabled:
            return None
        
        try:
            # Check cache first
            message_id = event.id
            if message_id in self._hash_cache:
                return self._hash_cache[message_id]
            
            # Download image
            buffer = BytesIO()
            # Check if client is available
            if not hasattr(event, 'client') or event.client is None:
                logger.error("Event client is None, cannot download media")
                return None
            
            await event.client.download_media(event.media, file=buffer)
            buffer.seek(0)
            
            # Open with PIL and compute hash
            if not IMAGE_PROCESSING_AVAILABLE:
                logger.warning("Image processing libraries not available")
                return None
                
            with Image.open(buffer) as img:
                # Convert to RGB if necessary
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Compute perceptual hash
                phash = imagehash.phash(img)
                hash_str = str(phash)
                
                # Cache the result
                self._hash_cache[message_id] = hash_str
                
                return hash_str
                
        except Exception as e:
            logger.error(f"Failed to compute image hash: {e}")
            return None
    
    async def _check_blocked_images(self, image_hash: str, pair: MessagePair) -> bool:
        """Check if image hash matches any blocked images"""
        try:
            async with self.db_manager.get_connection() as conn:
                # Check pair-specific blocks first
                cursor = await conn.execute('''
                    SELECT phash, similarity_threshold FROM blocked_images 
                    WHERE (pair_id = ? OR block_scope = 'global') 
                    AND (block_scope = 'pair' OR block_scope = 'global')
                ''', (pair.id,))
                
                blocked_images = await cursor.fetchall()
                
                if not blocked_images:
                    return False
                
                # Compare hashes
                for blocked_hash, threshold in blocked_images:
                    similarity = self._calculate_hash_similarity(image_hash, blocked_hash)
                    if similarity <= threshold:
                        return True
                
                return False
                
        except Exception as e:
            logger.error(f"Error checking blocked images: {e}")
            return False
    
    def _calculate_hash_similarity(self, hash1: str, hash2: str) -> int:
        """Calculate Hamming distance between two hashes"""
        if not self.enabled or not IMAGE_PROCESSING_AVAILABLE:
            return 100
        
        try:
            # Convert hex strings to imagehash objects
            ihash1 = imagehash.hex_to_hash(hash1)
            ihash2 = imagehash.hex_to_hash(hash2)
            
            # Calculate Hamming distance
            return ihash1 - ihash2
            
        except Exception as e:
            logger.error(f"Error calculating hash similarity: {e}")
            return 100  # Return high value on error
    
    async def _update_image_usage(self, image_hash: str, pair: MessagePair):
        """Update usage count for blocked image"""
        try:
            async with self.db_manager.get_connection() as conn:
                await conn.execute('''
                    UPDATE blocked_images 
                    SET usage_count = usage_count + 1 
                    WHERE phash = ? AND (pair_id = ? OR block_scope = 'global')
                ''', (image_hash, pair.id))
                await conn.commit()
                
        except Exception as e:
            logger.error(f"Failed to update image usage: {e}")
    
    async def get_blocked_images(self, pair_id: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get list of blocked images"""
        try:
            async with self.db_manager.get_connection() as conn:
                if pair_id:
                    cursor = await conn.execute('''
                        SELECT * FROM blocked_images 
                        WHERE pair_id = ? OR block_scope = 'global'
                        ORDER BY created_at DESC
                    ''', (pair_id,))
                else:
                    cursor = await conn.execute('''
                        SELECT * FROM blocked_images 
                        ORDER BY created_at DESC
                    ''')
                
                rows = await cursor.fetchall()
                
                blocked_images = []
                for row in rows:
                    blocked_images.append({
                        'id': row[0],
                        'phash': row[1],
                        'pair_id': row[2],
                        'description': row[3],
                        'blocked_by': row[4],
                        'usage_count': row[5],
                        'block_scope': row[6],
                        'similarity_threshold': row[7],
                        'created_at': row[8]
                    })
                
                return blocked_images
                
        except Exception as e:
            logger.error(f"Failed to get blocked images: {e}")
            return []
    
    def add_text_watermark(self, input_path: str, output_path: str, text: str) -> bool:
        """Add semi-transparent text watermark to image center"""
        if not self.enabled or not IMAGE_PROCESSING_AVAILABLE:
            logger.warning("[WATERMARK_DEBUG] Image processing not available, skipping watermark")
            return False
        
        try:
            # Verify input file exists and has content
            if not os.path.exists(input_path):
                logger.error(f"[WATERMARK_DEBUG] Input file does not exist: {input_path}")
                return False
            
            input_size = os.path.getsize(input_path)
            if input_size == 0:
                logger.error(f"[WATERMARK_DEBUG] Input file is empty: {input_path}")
                return False
            
            logger.info(f"[WATERMARK_DEBUG] Processing watermark - Input: {input_path} ({input_size} bytes), Output: {output_path}, Text: '{text}'")
            
            # Open base image and convert to RGBA for transparency support
            try:
                base = Image.open(input_path).convert("RGBA")
                logger.info(f"[WATERMARK_DEBUG] Image opened successfully - Size: {base.size}, Mode: {base.mode}")
            except Exception as open_error:
                logger.error(f"[WATERMARK_DEBUG] Failed to open image: {open_error}")
                return False
            
            # Create transparent overlay layer
            txt_layer = Image.new("RGBA", base.size, (255, 255, 255, 0))
            draw = ImageDraw.Draw(txt_layer)
            
            # Calculate font size (5% of image width)
            font_size = max(int(base.width * 0.05), 12)  # Minimum 12px font
            
            # Try to load system font, fallback to default
            font = None
            for font_path in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                            "/System/Library/Fonts/Arial.ttf", 
                            "/Windows/Fonts/arial.ttf"]:
                try:
                    if os.path.exists(font_path):
                        font = ImageFont.truetype(font_path, font_size)
                        break
                except:
                    continue
            
            # Use default font if no system font found
            if font is None:
                try:
                    font = ImageFont.load_default()
                except:
                    logger.warning("Could not load any font, using basic text rendering")
                    font = None
            
            # Get text dimensions
            if font:
                bbox = draw.textbbox((0, 0), text, font=font)
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
            else:
                # Estimate text size without font
                text_width = len(text) * (font_size // 2)
                text_height = font_size
            
            # Center text position
            x = (base.width - text_width) // 2
            y = (base.height - text_height) // 2
            
            # Draw semi-transparent white text (40% opacity = 102 alpha)
            text_color = (255, 255, 255, 102)
            
            if font:
                draw.text((x, y), text, font=font, fill=text_color)
            else:
                draw.text((x, y), text, fill=text_color)
            
            # Composite the layers
            watermarked = Image.alpha_composite(base, txt_layer)
            
            # Convert back to RGB and save as JPEG
            try:
                final_image = watermarked.convert("RGB")
                final_image.save(output_path, "JPEG", quality=95)
                
                # Verify output file was created and has content
                if os.path.exists(output_path):
                    output_size = os.path.getsize(output_path)
                    logger.info(f"[WATERMARK_DEBUG] Watermark completed successfully - Output: {output_path} ({output_size} bytes)")
                    if output_size > 0:
                        return True
                    else:
                        logger.error(f"[WATERMARK_DEBUG] Output file is empty: {output_path}")
                        return False
                else:
                    logger.error(f"[WATERMARK_DEBUG] Output file not created: {output_path}")
                    return False
                    
            except Exception as save_error:
                logger.error(f"[WATERMARK_DEBUG] Failed to save watermarked image: {save_error}")
                return False
            
        except Exception as e:
            import traceback
            logger.error(f"[WATERMARK_DEBUG] Watermark failed with exception: {e}")
            logger.error(f"[WATERMARK_DEBUG] Full traceback: {traceback.format_exc()}")
            return False
    
    async def cleanup_unused_blocks(self, days: int = 30):
        """Clean up unused image blocks"""
        try:
            from datetime import datetime, timedelta
            cutoff_date = (datetime.now() - timedelta(days=days)).isoformat()
            
            async with self.db_manager.get_connection() as conn:
                # Remove blocks that haven't been used recently
                cursor = await conn.execute('''
                    DELETE FROM blocked_images 
                    WHERE usage_count = 0 AND created_at < ?
                ''', (cutoff_date,))
                deleted_count = cursor.rowcount
                await conn.commit()
                
            logger.info(f"Cleaned up {deleted_count} unused image blocks older than {days} days")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup image blocks: {e}")
            return 0

    async def cleanup_orphaned_hashes(self) -> int:
        """Clean up orphaned image hashes that are no longer referenced"""
        try:
            async with self.db_manager.get_connection() as conn:
                # Find hashes that are not referenced by any active pairs
                cursor = await conn.execute('''
                    DELETE FROM blocked_images 
                    WHERE pair_id IS NOT NULL 
                    AND pair_id NOT IN (SELECT id FROM pairs WHERE status = 'active')
                ''')
                orphaned_count = cursor.rowcount
                await conn.commit()
                
                logger.info(f"Cleaned up {orphaned_count} orphaned image hashes")
                return orphaned_count
                
        except Exception as e:
            logger.error(f"Failed to cleanup orphaned hashes: {e}")
            return 0
    
    async def get_image_stats(self) -> Dict[str, int]:
        """Get image blocking statistics"""
        try:
            async with self.db_manager.get_connection() as conn:
                stats = {}
                
                # Total blocked images
                cursor = await conn.execute('SELECT COUNT(*) FROM blocked_images')
                result = await cursor.fetchone()
                stats['total_blocked'] = result[0] if result and result[0] else 0
                
                # Global blocks
                cursor = await conn.execute(
                    'SELECT COUNT(*) FROM blocked_images WHERE block_scope = "global"'
                )
                result = await cursor.fetchone()
                stats['global_blocks'] = result[0] if result and result[0] else 0
                
                # Pair-specific blocks
                cursor = await conn.execute(
                    'SELECT COUNT(*) FROM blocked_images WHERE block_scope = "pair"'
                )
                result = await cursor.fetchone()
                stats['pair_blocks'] = result[0] if result and result[0] else 0
                
                # Total usage
                cursor = await conn.execute('SELECT SUM(usage_count) FROM blocked_images')
                result = await cursor.fetchone()
                stats['total_blocks_triggered'] = result[0] if result and result[0] else 0
                
                return stats
                
        except Exception as e:
            logger.error(f"Failed to get image stats: {e}")
            return {}
    
    async def remove_image_block_by_hash(self, image_hash: str, pair_id: Optional[int] = None) -> bool:
        """Remove image block by hash"""
        try:
            async with self.db_manager.get_connection() as conn:
                if pair_id:
                    # Remove pair-specific block
                    await conn.execute('''
                        DELETE FROM blocked_images 
                        WHERE phash = ? AND pair_id = ?
                    ''', (image_hash, pair_id))
                else:
                    # Remove global block
                    await conn.execute('''
                        DELETE FROM blocked_images 
                        WHERE phash = ? AND block_scope = 'global'
                    ''', (image_hash,))
                
                await conn.commit()
                logger.info(f"Removed image block: {image_hash[:16]}...")
                return True
                
        except Exception as e:
            logger.error(f"Error removing image block: {e}")
            return False
    
    def clear_cache(self):
        """Clear hash cache"""
        self._hash_cache.clear()
        logger.info("Image hash cache cleared")
