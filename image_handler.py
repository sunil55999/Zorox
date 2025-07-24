"""
Image duplicate detection and blocking system
"""

import logging
import hashlib
from typing import Optional, Dict, List, Any
from io import BytesIO
from datetime import datetime

from database import DatabaseManager, MessagePair
from config import Config

logger = logging.getLogger(__name__)

# Try to import image processing libraries
try:
    import imagehash
    from PIL import Image
    IMAGE_PROCESSING_AVAILABLE = True
except ImportError:
    IMAGE_PROCESSING_AVAILABLE = False
    logger.warning("Image processing libraries not available. Image blocking disabled.")

class ImageHandler:
    """Image duplicate detection and blocking system"""
    
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
            # Only process photo messages
            if not hasattr(event, 'media') or not event.media:
                return False
            
            from telethon.tl.types import MessageMediaPhoto
            if not isinstance(event.media, MessageMediaPhoto):
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
    
    async def add_image_block(self, event, pair: MessagePair, 
                             description: str = "", 
                             blocked_by: str = "",
                             block_scope: str = "pair",
                             similarity_threshold: int = None) -> bool:
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
                    pair.id if block_scope == "pair" else None,
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
            await event.client.download_media(event.media, file=buffer)
            buffer.seek(0)
            
            # Open with PIL and compute hash
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
        if not self.enabled:
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
            
        except Exception as e:
            logger.error(f"Failed to cleanup image blocks: {e}")
    
    async def get_image_stats(self) -> Dict[str, int]:
        """Get image blocking statistics"""
        try:
            async with self.db_manager.get_connection() as conn:
                stats = {}
                
                # Total blocked images
                cursor = await conn.execute('SELECT COUNT(*) FROM blocked_images')
                stats['total_blocked'] = (await cursor.fetchone())[0]
                
                # Global blocks
                cursor = await conn.execute(
                    'SELECT COUNT(*) FROM blocked_images WHERE block_scope = "global"'
                )
                stats['global_blocks'] = (await cursor.fetchone())[0]
                
                # Pair-specific blocks
                cursor = await conn.execute(
                    'SELECT COUNT(*) FROM blocked_images WHERE block_scope = "pair"'
                )
                stats['pair_blocks'] = (await cursor.fetchone())[0]
                
                # Total usage
                cursor = await conn.execute('SELECT SUM(usage_count) FROM blocked_images')
                result = await cursor.fetchone()
                stats['total_blocks_triggered'] = result[0] if result[0] else 0
                
                return stats
                
        except Exception as e:
            logger.error(f"Failed to get image stats: {e}")
            return {}
    
    def clear_cache(self):
        """Clear hash cache"""
        self._hash_cache.clear()
        logger.info("Image hash cache cleared")
