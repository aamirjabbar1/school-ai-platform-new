#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LSS Chat Knowledge Base Population Script
Downloads PCTB, NBF, and OUP Teacher Guide PDFs and uploads them to the knowledge base.
"""

import os
import sys
import time
import json
import requests
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# ─── CONFIGURATION ────────────────────────────────────────────────────────────
API_BASE = "http://localhost:5000/api"
ADMIN_ID = "admin001"
ADMIN_PASS = "admin123"
DOWNLOAD_DIR = Path(__file__).parent.parent / "backend" / "knowledge_base_downloads"

# ─── PDF SOURCES ──────────────────────────────────────────────────────────────

PCTB_BOOKS = [
    # Grade 9
    {
        "url": "https://pctb.punjab.gov.pk/system/files/English%209-compressed.pdf",
        "title": "PCTB English Grade 9",
        "subject": "English",
        "class_level": "Grade 9",
        "description": "Punjab Curriculum and Textbook Board - English Grade 9 (English Medium)",
        "filename": "PCTB_English_Grade9.pdf",
    },
    {
        "url": "https://pctb.punjab.gov.pk/system/files/Physics%209.pdf",
        "title": "PCTB Physics Grade 9",
        "subject": "Physics",
        "class_level": "Grade 9",
        "description": "Punjab Curriculum and Textbook Board - Physics Grade 9",
        "filename": "PCTB_Physics_Grade9.pdf",
    },
    {
        "url": "https://pctb.punjab.gov.pk/system/files/General%20Science%209-10%20EM%20compressed.pdf",
        "title": "PCTB General Science Grade 9-10",
        "subject": "Science",
        "class_level": "Grade 9",
        "description": "Punjab Curriculum and Textbook Board - General Science Grade 9-10 (English Medium)",
        "filename": "PCTB_GeneralScience_Grade9-10_EM.pdf",
    },
    {
        "url": "https://pctb.punjab.gov.pk/system/files/Computer%20Science%209th%20Final%20EM_0.pdf",
        "title": "PCTB Computer Science Grade 9",
        "subject": "Computer Science",
        "class_level": "Grade 9",
        "description": "Punjab Curriculum and Textbook Board - Computer Science Grade 9 (English Medium)",
        "filename": "PCTB_ComputerScience_Grade9.pdf",
    },
    {
        "url": "https://pctb.punjab.gov.pk/system/files/Islamiat%20Lazmi%209-10.pdf",
        "title": "PCTB Islamiat Lazmi Grade 9-10",
        "subject": "Islamiat",
        "class_level": "Grade 9",
        "description": "Punjab Curriculum and Textbook Board - Islamiat Lazmi Grade 9-10",
        "filename": "PCTB_Islamiat_Grade9-10.pdf",
    },
    {
        "url": "https://pctb.punjab.gov.pk/system/files/Urdu%209.pdf",
        "title": "PCTB Urdu Grade 9",
        "subject": "Urdu",
        "class_level": "Grade 9",
        "description": "Punjab Curriculum and Textbook Board - Urdu Grade 9",
        "filename": "PCTB_Urdu_Grade9.pdf",
    },
    # Grade 10 — try common URL patterns
    {
        "url": "https://pctb.punjab.gov.pk/system/files/English%2010-compressed.pdf",
        "title": "PCTB English Grade 10",
        "subject": "English",
        "class_level": "Grade 10",
        "description": "Punjab Curriculum and Textbook Board - English Grade 10",
        "filename": "PCTB_English_Grade10.pdf",
    },
    {
        "url": "https://pctb.punjab.gov.pk/system/files/Physics%2010.pdf",
        "title": "PCTB Physics Grade 10",
        "subject": "Physics",
        "class_level": "Grade 10",
        "description": "Punjab Curriculum and Textbook Board - Physics Grade 10",
        "filename": "PCTB_Physics_Grade10.pdf",
    },
    {
        "url": "https://pctb.punjab.gov.pk/system/files/Chemistry%2010.pdf",
        "title": "PCTB Chemistry Grade 10",
        "subject": "Chemistry",
        "class_level": "Grade 10",
        "description": "Punjab Curriculum and Textbook Board - Chemistry Grade 10",
        "filename": "PCTB_Chemistry_Grade10.pdf",
    },
    {
        "url": "https://pctb.punjab.gov.pk/system/files/Biology%2010.pdf",
        "title": "PCTB Biology Grade 10",
        "subject": "Biology",
        "class_level": "Grade 10",
        "description": "Punjab Curriculum and Textbook Board - Biology Grade 10",
        "filename": "PCTB_Biology_Grade10.pdf",
    },
    {
        "url": "https://pctb.punjab.gov.pk/system/files/Mathematics%2010.pdf",
        "title": "PCTB Mathematics Grade 10",
        "subject": "Mathematics",
        "class_level": "Grade 10",
        "description": "Punjab Curriculum and Textbook Board - Mathematics Grade 10",
        "filename": "PCTB_Mathematics_Grade10.pdf",
    },
    {
        "url": "https://pctb.punjab.gov.pk/system/files/Computer%20Science%2010th%20Final%20EM.pdf",
        "title": "PCTB Computer Science Grade 10",
        "subject": "Computer Science",
        "class_level": "Grade 10",
        "description": "Punjab Curriculum and Textbook Board - Computer Science Grade 10 (English Medium)",
        "filename": "PCTB_ComputerScience_Grade10.pdf",
    },
    {
        "url": "https://pctb.punjab.gov.pk/system/files/Urdu%2010.pdf",
        "title": "PCTB Urdu Grade 10",
        "subject": "Urdu",
        "class_level": "Grade 10",
        "description": "Punjab Curriculum and Textbook Board - Urdu Grade 10",
        "filename": "PCTB_Urdu_Grade10.pdf",
    },
]

NBF_BOOKS = [
    # Grade 9
    {
        "url": "https://www.nbf.org.pk/sites/default/files/Computer%20Grade%209-1.pdf",
        "title": "NBF Computer Science Grade 9",
        "subject": "Computer Science",
        "class_level": "Grade 9",
        "description": "National Book Foundation - Computer Science Grade 9",
        "filename": "NBF_ComputerScience_Grade9.pdf",
    },
    {
        "url": "https://www.nbf.org.pk/sites/default/files/General%20Science%209.pdf",
        "title": "NBF General Science Grade 9",
        "subject": "Science",
        "class_level": "Grade 9",
        "description": "National Book Foundation - General Science Grade 9",
        "filename": "NBF_GeneralScience_Grade9.pdf",
    },
    {
        "url": "https://www.nbf.org.pk/sites/default/files/Economic%209_0.pdf",
        "title": "NBF Economics Grade 9",
        "subject": "Economics",
        "class_level": "Grade 9",
        "description": "National Book Foundation - Economics Grade 9",
        "filename": "NBF_Economics_Grade9.pdf",
    },
    {
        "url": "https://www.nbf.org.pk/sites/default/files/English%209.pdf",
        "title": "NBF English Grade 9",
        "subject": "English",
        "class_level": "Grade 9",
        "description": "National Book Foundation - English Grade 9",
        "filename": "NBF_English_Grade9.pdf",
    },
    {
        "url": "https://www.nbf.org.pk/sites/default/files/Urdu%209.pdf",
        "title": "NBF Urdu Grade 9",
        "subject": "Urdu",
        "class_level": "Grade 9",
        "description": "National Book Foundation - Urdu Grade 9",
        "filename": "NBF_Urdu_Grade9.pdf",
    },
    {
        "url": "https://www.nbf.org.pk/sites/default/files/Physics%209.pdf",
        "title": "NBF Physics Grade 9",
        "subject": "Physics",
        "class_level": "Grade 9",
        "description": "National Book Foundation - Physics Grade 9",
        "filename": "NBF_Physics_Grade9.pdf",
    },
    {
        "url": "https://www.nbf.org.pk/sites/default/files/Mathematics%209.pdf",
        "title": "NBF Mathematics Grade 9",
        "subject": "Mathematics",
        "class_level": "Grade 9",
        "description": "National Book Foundation - Mathematics Grade 9",
        "filename": "NBF_Mathematics_Grade9.pdf",
    },
    {
        "url": "https://www.nbf.org.pk/sites/default/files/Chemistry%209.pdf",
        "title": "NBF Chemistry Grade 9",
        "subject": "Chemistry",
        "class_level": "Grade 9",
        "description": "National Book Foundation - Chemistry Grade 9",
        "filename": "NBF_Chemistry_Grade9.pdf",
    },
    {
        "url": "https://www.nbf.org.pk/sites/default/files/Biology%209.pdf",
        "title": "NBF Biology Grade 9",
        "subject": "Biology",
        "class_level": "Grade 9",
        "description": "National Book Foundation - Biology Grade 9",
        "filename": "NBF_Biology_Grade9.pdf",
    },
    # Grade 10
    {
        "url": "https://www.nbf.org.pk/sites/default/files/English%2010.pdf",
        "title": "NBF English Grade 10",
        "subject": "English",
        "class_level": "Grade 10",
        "description": "National Book Foundation - English Grade 10",
        "filename": "NBF_English_Grade10.pdf",
    },
    {
        "url": "https://www.nbf.org.pk/sites/default/files/Physics%2010.pdf",
        "title": "NBF Physics Grade 10",
        "subject": "Physics",
        "class_level": "Grade 10",
        "description": "National Book Foundation - Physics Grade 10",
        "filename": "NBF_Physics_Grade10.pdf",
    },
    {
        "url": "https://www.nbf.org.pk/sites/default/files/Chemistry%2010.pdf",
        "title": "NBF Chemistry Grade 10",
        "subject": "Chemistry",
        "class_level": "Grade 10",
        "description": "National Book Foundation - Chemistry Grade 10",
        "filename": "NBF_Chemistry_Grade10.pdf",
    },
    {
        "url": "https://www.nbf.org.pk/sites/default/files/Biology%2010.pdf",
        "title": "NBF Biology Grade 10",
        "subject": "Biology",
        "class_level": "Grade 10",
        "description": "National Book Foundation - Biology Grade 10",
        "filename": "NBF_Biology_Grade10.pdf",
    },
    {
        "url": "https://www.nbf.org.pk/sites/default/files/Mathematics%2010.pdf",
        "title": "NBF Mathematics Grade 10",
        "subject": "Mathematics",
        "class_level": "Grade 10",
        "description": "National Book Foundation - Mathematics Grade 10",
        "filename": "NBF_Mathematics_Grade10.pdf",
    },
    {
        "url": "https://www.nbf.org.pk/sites/default/files/Computer%20Grade%2010.pdf",
        "title": "NBF Computer Science Grade 10",
        "subject": "Computer Science",
        "class_level": "Grade 10",
        "description": "National Book Foundation - Computer Science Grade 10",
        "filename": "NBF_ComputerScience_Grade10.pdf",
    },
    {
        "url": "https://www.nbf.org.pk/sites/default/files/Urdu%2010.pdf",
        "title": "NBF Urdu Grade 10",
        "subject": "Urdu",
        "class_level": "Grade 10",
        "description": "National Book Foundation - Urdu Grade 10",
        "filename": "NBF_Urdu_Grade10.pdf",
    },
    {
        "url": "https://www.nbf.org.pk/sites/default/files/Pakistan%20Studies%2010.pdf",
        "title": "NBF Pakistan Studies Grade 10",
        "subject": "Pakistan Studies",
        "class_level": "Grade 10",
        "description": "National Book Foundation - Pakistan Studies Grade 10",
        "filename": "NBF_PakistanStudies_Grade10.pdf",
    },
]

# OUP Teacher Guides — matching LSS booklist series
# URLs will be added by add_oup_guides() after fetching from the OUP site
OUP_TEACHER_GUIDES = []

# ─── HELPER FUNCTIONS ─────────────────────────────────────────────────────────

def login():
    """Get JWT token from backend."""
    print(f"Logging in as {ADMIN_ID}...")
    resp = requests.post(f"{API_BASE}/auth/login", json={
        "login_id": ADMIN_ID,
        "password": ADMIN_PASS,
    }, timeout=10)
    resp.raise_for_status()
    token = resp.json()["token"]
    print("✅ Login successful")
    return token


def download_pdf(url, dest_path, retries=3):
    """Download a PDF file, return True on success."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/pdf,*/*",
    }
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=60, stream=True,
                                verify=False)  # some .pk sites have SSL issues
            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "")
                if "pdf" in content_type or "octet-stream" in content_type or "application" in content_type:
                    with open(dest_path, "wb") as f:
                        for chunk in resp.iter_content(8192):
                            f.write(chunk)
                    size_kb = os.path.getsize(dest_path) / 1024
                    if size_kb < 5:
                        os.remove(dest_path)
                        print(f"  ⚠️  File too small ({size_kb:.1f}KB), likely not a real PDF")
                        return False
                    print(f"  ✅ Downloaded {size_kb:.0f}KB")
                    return True
                else:
                    print(f"  ⚠️  Unexpected content-type: {content_type}")
                    return False
            else:
                print(f"  ⚠️  HTTP {resp.status_code} (attempt {attempt+1}/{retries})")
                time.sleep(2)
        except Exception as e:
            print(f"  ❌ Error: {e} (attempt {attempt+1}/{retries})")
            time.sleep(3)
    return False


def upload_document(token, file_path, title, subject, class_level, description):
    """Upload a PDF to the knowledge base via the API."""
    headers = {"Authorization": f"Bearer {token}"}
    with open(file_path, "rb") as f:
        files = {"document": (os.path.basename(file_path), f, "application/pdf")}
        data = {
            "title": title,
            "subject": subject,
            "class_level": class_level,
            "description": description,
        }
        resp = requests.post(
            f"{API_BASE}/documents/upload",
            headers=headers,
            files=files,
            data=data,
            timeout=120,
        )
    if resp.status_code in (200, 201):
        doc = resp.json()
        print(f"  ✅ Uploaded → ID {doc.get('id')}, ingestion in progress")
        return True
    else:
        print(f"  ❌ Upload failed: {resp.status_code} — {resp.text[:200]}")
        return False


def process_book_list(books, source_name, token, subdir):
    """Download and upload a list of books."""
    dest_dir = DOWNLOAD_DIR / subdir
    dest_dir.mkdir(parents=True, exist_ok=True)

    downloaded = 0
    uploaded = 0
    failed_download = []
    failed_upload = []

    for book in books:
        title = book["title"]
        filename = book["filename"]
        dest_path = dest_dir / filename

        print(f"\n📥 {title}")
        print(f"   URL: {book['url']}")

        # Skip if already downloaded
        if dest_path.exists():
            size_kb = os.path.getsize(dest_path) / 1024
            print(f"  ✅ Already downloaded ({size_kb:.0f}KB)")
        else:
            if not download_pdf(book["url"], dest_path):
                failed_download.append(title)
                continue

        downloaded += 1

        # Upload to knowledge base
        print(f"  📤 Uploading to knowledge base...")
        if upload_document(
            token, dest_path,
            book["title"], book["subject"],
            book["class_level"], book["description"]
        ):
            uploaded += 1
        else:
            failed_upload.append(title)

        time.sleep(1)  # Be polite to the server

    print(f"\n{'='*60}")
    print(f"{source_name} Summary: {downloaded} downloaded, {uploaded} uploaded")
    if failed_download:
        print(f"  Failed downloads ({len(failed_download)}): {', '.join(failed_download)}")
    if failed_upload:
        print(f"  Failed uploads ({len(failed_upload)}): {', '.join(failed_upload)}")

    return downloaded, uploaded


def main():
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("LSS Chat Knowledge Base Population")
    print("=" * 60)

    # Login
    try:
        token = login()
    except Exception as e:
        print(f"❌ Login failed: {e}")
        print("Make sure the backend server is running on port 5000.")
        sys.exit(1)

    total_downloaded = 0
    total_uploaded = 0

    # 1. PCTB Books
    print("\n" + "="*60)
    print("PCTB (Punjab Curriculum and Textbook Board)")
    print("="*60)
    d, u = process_book_list(PCTB_BOOKS, "PCTB", token, "PCTB")
    total_downloaded += d
    total_uploaded += u

    # 2. NBF Books
    print("\n" + "="*60)
    print("NBF (National Book Foundation)")
    print("="*60)
    d, u = process_book_list(NBF_BOOKS, "NBF", token, "NBF")
    total_downloaded += d
    total_uploaded += u

    # 3. OUP Teacher Guides (if any loaded)
    if OUP_TEACHER_GUIDES:
        print("\n" + "="*60)
        print("OUP Teacher Guides")
        print("="*60)
        d, u = process_book_list(OUP_TEACHER_GUIDES, "OUP", token, "OUP_TeacherGuides")
        total_downloaded += d
        total_uploaded += u

    print("\n" + "="*60)
    print(f"TOTAL: {total_downloaded} files downloaded, {total_uploaded} uploaded to knowledge base")
    print("="*60)
    print("\nNote: Ingestion runs in background. Check Admin > Knowledge Base to monitor progress.")


if __name__ == "__main__":
    main()
