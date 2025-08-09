#!/usr/bin/env python3
"""
Diagnostic test for media processing failures
Runs isolated tests on the watermarking and filtering pipeline
"""

import os
import sys
import asyncio
import logging
import tempfile
from pathlib import Path
from PIL import Image, ImageDraw
import time

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from image_handler import ImageHandler
from database import DatabaseManager, MessagePair
from config import Config
from filters import MessageFilter

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MediaProcessingDiagnostic:
    """Comprehensive diagnostic for media processing failures"""
    
    def __init__(self):
        self.config = Config()
        self.db_manager = None
        self.image_handler = None
        self.message_filter = None
        self.results = {
            'watermark_tests': {},
            'file_tests': {},
            'processing_stats': {},
            'error_patterns': []
        }
    
    async def initialize(self):
        """Initialize components"""
        try:
            self.db_manager = DatabaseManager("bot.db")
            await self.db_manager.initialize()
            
            self.image_handler = ImageHandler(self.db_manager, self.config)
            self.message_filter = MessageFilter(self.db_manager, self.config)
            await self.message_filter.initialize()
            
            logger.info("Diagnostic components initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"Failed to initialize components: {e}")
            return False
    
    def create_test_images(self):
        """Create test images with different formats and characteristics"""
        test_images = {}
        
        # Create temporary directory
        temp_dir = tempfile.mkdtemp(prefix="media_test_")
        
        # Test image 1: Simple JPEG
        img1 = Image.new('RGB', (800, 600), color='red')
        img1_path = os.path.join(temp_dir, 'test_jpeg.jpg')
        img1.save(img1_path, 'JPEG', quality=95)
        test_images['jpeg'] = img1_path
        
        # Test image 2: PNG with transparency  
        img2 = Image.new('RGBA', (400, 300), color=(0, 255, 0, 128))
        img2_path = os.path.join(temp_dir, 'test_png.png')
        img2.save(img2_path, 'PNG')
        test_images['png'] = img2_path
        
        # Test image 3: Large image
        img3 = Image.new('RGB', (2000, 1500), color='blue')
        img3_path = os.path.join(temp_dir, 'test_large.jpg')
        img3.save(img3_path, 'JPEG', quality=90)
        test_images['large'] = img3_path
        
        # Test image 4: Small image
        img4 = Image.new('RGB', (100, 100), color='yellow')
        img4_path = os.path.join(temp_dir, 'test_small.jpg')
        img4.save(img4_path, 'JPEG', quality=95)
        test_images['small'] = img4_path
        
        # Test image 5: Corrupted file (empty)
        corrupt_path = os.path.join(temp_dir, 'corrupt.jpg')
        with open(corrupt_path, 'wb') as f:
            f.write(b'')
        test_images['corrupt'] = corrupt_path
        
        return test_images, temp_dir
    
    async def test_watermarking(self, test_images: dict):
        """Test watermarking with different image formats"""
        logger.info("=== Starting Watermark Tests ===")
        
        watermark_texts = [
            "@TestWatermark",
            "@Traders_Hive", 
            "Very Long Watermark Text That Should Scale",
            "🔥",  # Unicode
            ""  # Empty text
        ]
        
        for img_type, img_path in test_images.items():
            for text in watermark_texts:
                test_key = f"{img_type}_{text[:10]}"
                start_time = time.time()
                
                try:
                    # Skip empty text for corrupted images
                    if not text and img_type == 'corrupt':
                        continue
                    
                    output_path = img_path.replace('.', f'_watermarked_{len(text)}.')
                    if not output_path.endswith('.jpg'):
                        output_path = output_path.rsplit('.', 1)[0] + '.jpg'
                    
                    logger.info(f"Testing watermark: {img_type} with '{text}' -> {output_path}")
                    
                    success = self.image_handler.add_text_watermark(img_path, output_path, text)
                    process_time = time.time() - start_time
                    
                    # Verify output
                    output_exists = os.path.exists(output_path)
                    output_size = os.path.getsize(output_path) if output_exists else 0
                    
                    self.results['watermark_tests'][test_key] = {
                        'input_type': img_type,
                        'text': text,
                        'success': success,
                        'output_exists': output_exists,
                        'output_size': output_size,
                        'process_time': process_time,
                        'input_path': img_path,
                        'output_path': output_path
                    }
                    
                    if success:
                        logger.info(f"✅ Watermark success: {test_key} ({process_time:.3f}s, {output_size} bytes)")
                    else:
                        logger.error(f"❌ Watermark failed: {test_key} ({process_time:.3f}s)")
                        
                except Exception as e:
                    process_time = time.time() - start_time
                    logger.error(f"❌ Watermark exception: {test_key} - {e}")
                    self.results['watermark_tests'][test_key] = {
                        'input_type': img_type,
                        'text': text,
                        'success': False,
                        'error': str(e),
                        'process_time': process_time
                    }
    
    async def test_file_operations(self, test_images: dict):
        """Test file operations and format support"""
        logger.info("=== Starting File Operation Tests ===")
        
        for img_type, img_path in test_images.items():
            test_results = {}
            
            # Test file existence and size
            exists = os.path.exists(img_path)
            size = os.path.getsize(img_path) if exists else 0
            
            # Test PIL image opening
            can_open = False
            format_type = None
            mode = None
            dimensions = None
            
            try:
                with Image.open(img_path) as img:
                    can_open = True
                    format_type = img.format
                    mode = img.mode
                    dimensions = img.size
            except Exception as e:
                logger.warning(f"PIL open failed for {img_type}: {e}")
            
            test_results = {
                'exists': exists,
                'size': size,
                'can_open': can_open,
                'format': format_type,
                'mode': mode,
                'dimensions': dimensions,
                'path': img_path
            }
            
            self.results['file_tests'][img_type] = test_results
            logger.info(f"File test {img_type}: Exists={exists}, Size={size}, CanOpen={can_open}, Format={format_type}")
    
    def analyze_results(self):
        """Analyze test results for patterns"""
        logger.info("=== Analyzing Results ===")
        
        # Watermark success rates
        watermark_results = self.results['watermark_tests']
        total_tests = len(watermark_results)
        successful_tests = sum(1 for r in watermark_results.values() if r.get('success', False))
        
        logger.info(f"Watermark Success Rate: {successful_tests}/{total_tests} ({(successful_tests/total_tests)*100:.1f}%)")
        
        # Failures by image type
        failures_by_type = {}
        for test_key, result in watermark_results.items():
            if not result.get('success', False):
                img_type = result.get('input_type', 'unknown')
                failures_by_type[img_type] = failures_by_type.get(img_type, 0) + 1
        
        logger.info("Failures by image type:")
        for img_type, count in failures_by_type.items():
            logger.info(f"  {img_type}: {count} failures")
        
        # Average processing times
        times_by_type = {}
        for test_key, result in watermark_results.items():
            img_type = result.get('input_type', 'unknown')
            process_time = result.get('process_time', 0)
            if img_type not in times_by_type:
                times_by_type[img_type] = []
            times_by_type[img_type].append(process_time)
        
        logger.info("Average processing times:")
        for img_type, times in times_by_type.items():
            avg_time = sum(times) / len(times) if times else 0
            logger.info(f"  {img_type}: {avg_time:.3f}s average")
        
        # Common error patterns
        error_patterns = {}
        for test_key, result in watermark_results.items():
            if not result.get('success', False) and 'error' in result:
                error_msg = result['error']
                error_patterns[error_msg] = error_patterns.get(error_msg, 0) + 1
        
        if error_patterns:
            logger.info("Common error patterns:")
            for error, count in error_patterns.items():
                logger.info(f"  {error}: {count} occurrences")
        
        return {
            'total_tests': total_tests,
            'successful_tests': successful_tests,
            'success_rate': (successful_tests/total_tests)*100 if total_tests > 0 else 0,
            'failures_by_type': failures_by_type,
            'average_times': {img_type: sum(times)/len(times) for img_type, times in times_by_type.items()},
            'error_patterns': error_patterns
        }
    
    def cleanup(self, temp_dir: str):
        """Clean up test files"""
        try:
            import shutil
            shutil.rmtree(temp_dir)
            logger.info(f"Cleaned up test directory: {temp_dir}")
        except Exception as e:
            logger.warning(f"Failed to cleanup {temp_dir}: {e}")

async def main():
    """Run diagnostic tests"""
    diagnostic = MediaProcessingDiagnostic()
    
    # Initialize
    if not await diagnostic.initialize():
        logger.error("Failed to initialize diagnostic")
        return 1
    
    # Create test images
    logger.info("Creating test images...")
    test_images, temp_dir = diagnostic.create_test_images()
    logger.info(f"Created {len(test_images)} test images in {temp_dir}")
    
    try:
        # Run tests
        await diagnostic.test_file_operations(test_images)
        await diagnostic.test_watermarking(test_images)
        
        # Analyze results
        analysis = diagnostic.analyze_results()
        
        # Final summary
        logger.info("=== DIAGNOSTIC SUMMARY ===")
        logger.info(f"Overall Success Rate: {analysis['success_rate']:.1f}%")
        logger.info(f"Total Tests: {analysis['total_tests']}")
        logger.info(f"Successful: {analysis['successful_tests']}")
        logger.info(f"Failed: {analysis['total_tests'] - analysis['successful_tests']}")
        
        if analysis['success_rate'] < 70:
            logger.error("❌ CRITICAL: Low success rate detected!")
            return 1
        elif analysis['success_rate'] < 90:
            logger.warning("⚠️  WARNING: Moderate success rate")
            return 0
        else:
            logger.info("✅ SUCCESS: High success rate")
            return 0
            
    finally:
        # Cleanup
        diagnostic.cleanup(temp_dir)

if __name__ == '__main__':
    exit_code = asyncio.run(main())
    sys.exit(exit_code)