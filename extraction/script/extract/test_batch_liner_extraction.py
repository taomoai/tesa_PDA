"""
Batch extraction test for Liner type files
Configure TARGET_FILES to specify which files to extract
"""
import sys
import asyncio
import json
import logging
import time
from pathlib import Path
from datetime import datetime

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi_app.modules.pda_service.service import PdaTaskService
from fastapi_app.modules.pda_service.extraction_config import DocumentType
from fastapi_app.core.database import init_async_database, close_async_database

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION: Specify which files to extract
# ============================================================================
# Set to None to extract all PDF files in tests/files/
# Set to a list of filenames to extract only specific files
# Examples:
#   TARGET_FILES = None  # Extract all files
#   TARGET_FILES = ["20291.PDF"]  # Extract only 20291.PDF
#   TARGET_FILES = ["21103-9xxxx-xx 2025signed.pdf", "21104-9xxxx-xx 2025signed.pdf"]
# ============================================================================
TARGET_FILES = None  # 问题1: 20291 - 可读文本的 PDF

async def extract_all_liner_files():
    """Extract all Liner type files from tests/files directory"""

    start_time = time.time()
    logger.info(f"\n{'='*80}")
    logger.info(f"🚀 Starting Batch Liner Extraction")
    logger.info(f"Start Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"{'='*80}\n")

    # Initialize database
    logger.info("📦 Initializing database connection...")
    await init_async_database()
    logger.info("✅ Database connection established\n")

    try:
        test_files_dir = Path("tests/files")
        output_dir = Path("output")
        output_dir.mkdir(exist_ok=True)

        # Find PDF files based on TARGET_FILES configuration
        logger.info(f"🔍 Scanning {test_files_dir} for PDF files...")

        if TARGET_FILES is None:
            # Extract all PDF files
            all_pdf_files = list(test_files_dir.glob("*.pdf")) + list(test_files_dir.glob("*.PDF"))
            all_pdf_files = sorted(all_pdf_files)
            logger.info(f"✅ Found {len(all_pdf_files)} PDF files to extract as Liner type\n")
        else:
            # Extract only specified files
            all_pdf_files = []
            for filename in TARGET_FILES:
                file_path = test_files_dir / filename
                if file_path.exists():
                    all_pdf_files.append(file_path)
                    logger.info(f"✅ Found target file: {filename}")
                else:
                    logger.warning(f"⚠️  Target file not found: {filename}")

            if not all_pdf_files:
                logger.error("❌ No target files found in tests/files directory")
                return

            logger.info(f"✅ Ready to extract {len(all_pdf_files)} target file(s)\n")

        service = PdaTaskService()
        results = []

        for idx, pdf_file in enumerate(all_pdf_files, 1):
            file_size_mb = pdf_file.stat().st_size / (1024 * 1024)
            logger.info(f"\n{'='*80}")
            logger.info(f"📄 [{idx}/{len(all_pdf_files)}] Processing: {pdf_file.name}")
            logger.info(f"   File Size: {file_size_mb:.2f} MB")
            logger.info(f"   Document Type: LINER")
            logger.info(f"   Status: Starting extraction...")
            logger.info(f"{'='*80}")

            file_start_time = time.time()

            try:
                # Extract PDF with explicit document type
                logger.info("   ⏳ Calling extraction service...")
                result = await service.extract_pdf_to_json(
                    pdf_path=str(pdf_file),
                    output_dir=str(output_dir),
                    doc_type=DocumentType.LINER
                )

                file_elapsed = time.time() - file_start_time

                if result:
                    logger.info(f"   ✅ Successfully extracted: {pdf_file.name}")
                    logger.info(f"   ⏱️  Extraction time: {file_elapsed:.2f}s")
                    logger.info(f"   📊 Sections extracted: {', '.join(result.keys())}")
                    results.append({
                        "file": pdf_file.name,
                        "status": "success",
                        "sections": list(result.keys()),
                        "extraction_time_seconds": file_elapsed
                    })
                else:
                    logger.error(f"   ❌ Failed to extract: {pdf_file.name}")
                    logger.error(f"   ⏱️  Extraction time: {file_elapsed:.2f}s")
                    results.append({
                        "file": pdf_file.name,
                        "status": "failed",
                        "error": "No result returned",
                        "extraction_time_seconds": file_elapsed
                    })

            except Exception as e:
                file_elapsed = time.time() - file_start_time
                logger.error(f"   ❌ Error extracting {pdf_file.name}: {str(e)}")
                logger.error(f"   ⏱️  Extraction time: {file_elapsed:.2f}s")
                results.append({
                    "file": pdf_file.name,
                    "status": "error",
                    "error": str(e),
                    "extraction_time_seconds": file_elapsed
                })
        
        # Print summary
        total_elapsed = time.time() - start_time
        logger.info(f"\n{'='*80}")
        logger.info("📊 BATCH EXTRACTION SUMMARY")
        logger.info(f"{'='*80}")

        success_count = sum(1 for r in results if r["status"] == "success")
        failed_count = sum(1 for r in results if r["status"] in ["failed", "error"])
        total_extraction_time = sum(r.get("extraction_time_seconds", 0) for r in results)

        logger.info(f"📈 Statistics:")
        logger.info(f"   Total files: {len(results)}")
        logger.info(f"   ✅ Success: {success_count}")
        logger.info(f"   ❌ Failed/Error: {failed_count}")
        logger.info(f"   Success rate: {(success_count/len(results)*100):.1f}%")

        logger.info(f"\n⏱️  Timing:")
        logger.info(f"   Total extraction time: {total_extraction_time:.2f}s")
        logger.info(f"   Total elapsed time: {total_elapsed:.2f}s")
        logger.info(f"   Average per file: {(total_extraction_time/len(results)):.2f}s")

        logger.info(f"\n📋 Detailed results:")
        for idx, result in enumerate(results, 1):
            status_icon = "✅" if result["status"] == "success" else "❌"
            extraction_time = result.get("extraction_time_seconds", 0)
            logger.info(f"  [{idx}] {status_icon} {result['file']} ({extraction_time:.2f}s)")
            if result["status"] == "success":
                logger.info(f"       Sections: {', '.join(result['sections'])}")
            else:
                logger.info(f"       Error: {result.get('error', 'Unknown error')}")
        
        # Save summary to file
        summary_file = output_dir / "batch_extraction_summary.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump({
                "total": len(results),
                "success": success_count,
                "failed": failed_count,
                "total_extraction_time_seconds": total_extraction_time,
                "total_elapsed_time_seconds": total_elapsed,
                "end_time": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "results": results
            }, f, indent=2, ensure_ascii=False)

        logger.info(f"\n💾 Summary saved to: {summary_file}")
        logger.info(f"\n{'='*80}")
        logger.info(f"✅ Batch extraction completed!")
        logger.info(f"End Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'='*80}\n")
    
    finally:
        # Close database connection
        await close_async_database()

if __name__ == "__main__":
    asyncio.run(extract_all_liner_files())
