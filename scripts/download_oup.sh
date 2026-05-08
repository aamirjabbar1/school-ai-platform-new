#!/bin/bash
# OUP Teacher Guides Download & Upload Script
# These are digital PDFs (text-based) from Oxford University Press Pakistan

API="http://localhost:5000/api"
DOWNDIR="$(dirname "$0")/../backend/knowledge_base_downloads/OUP"

echo "Logging in..."
TOKEN=$(curl -s -X POST "$API/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"login_id":"admin001","password":"admin123"}' | python -c "import sys,json; print(json.load(sys.stdin)['token'])")

if [ -z "$TOKEN" ]; then
  echo "ERROR: Login failed"
  exit 1
fi
echo "Login OK"

# ──────────────────────────────────────────
# Helper function
# Usage: process_book <url> <filename> <subdir> <title> <subject> <class_level> <desc>
# ──────────────────────────────────────────
process_book() {
  local URL="$1"
  local FNAME="$2"
  local SUBDIR="$3"
  local TITLE="$4"
  local SUBJECT="$5"
  local CLASS="$6"
  local DESC="$7"
  local DEST="$DOWNDIR/$SUBDIR/$FNAME"

  mkdir -p "$DOWNDIR/$SUBDIR"

  echo ""
  echo "==> $TITLE"

  if [ -f "$DEST" ]; then
    SIZE=$(du -k "$DEST" | cut -f1)
    echo "  Already downloaded (${SIZE}KB)"
  else
    curl -s -L --max-time 60 -o "$DEST" "$URL"
    if [ $? -eq 0 ] && [ -f "$DEST" ]; then
      SIZE=$(du -k "$DEST" | cut -f1)
      if [ "$SIZE" -lt 10 ]; then
        echo "  SKIP: Too small (${SIZE}KB)"
        rm -f "$DEST"
        return
      fi
      echo "  Downloaded (${SIZE}KB)"
    else
      echo "  FAILED to download"
      rm -f "$DEST" 2>/dev/null
      return
    fi
  fi

  echo "  Uploading..."
  RESULT=$(curl -s -X POST "$API/documents/upload" \
    -H "Authorization: Bearer $TOKEN" \
    -F "document=@$DEST;type=application/pdf" \
    -F "title=$TITLE" \
    -F "subject=$SUBJECT" \
    -F "class_level=$CLASS" \
    -F "description=$DESC")

  ID=$(echo "$RESULT" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('id','ERR'))" 2>/dev/null)
  if [ "$ID" != "ERR" ] && [ -n "$ID" ]; then
    echo "  Uploaded (ID: $ID)"
  else
    echo "  Upload result: $RESULT"
  fi
}

# ══════════════════════════════════════════
# NEW OXFORD MODERN ENGLISH 3rd Edition
# LSS Booklist: Grade 1–7
# ══════════════════════════════════════════
echo ""; echo "=============================="; echo "New Oxford Modern English - Teacher Guides"; echo "=============================="

BASE="https://oup.com.pk/media/teaching-guides/New%20Oxford%20Modern%20English%203rd%20Edition"

process_book "$BASE/Teaching%20Guide%201.pdf" "NOME_TG1.pdf" "NOME" \
  "New Oxford Modern English Teaching Guide 1" "English" "Grade 1" \
  "OUP Pakistan - New Oxford Modern English 3rd Ed Teacher Guide Grade 1"

process_book "$BASE/Teaching%20Guide%202.pdf" "NOME_TG2.pdf" "NOME" \
  "New Oxford Modern English Teaching Guide 2" "English" "Grade 2" \
  "OUP Pakistan - New Oxford Modern English 3rd Ed Teacher Guide Grade 2"

process_book "$BASE/Teaching%20Guide%203.pdf" "NOME_TG3.pdf" "NOME" \
  "New Oxford Modern English Teaching Guide 3" "English" "Grade 3" \
  "OUP Pakistan - New Oxford Modern English 3rd Ed Teacher Guide Grade 3"

process_book "$BASE/Teaching%20Guide%204.pdf" "NOME_TG4.pdf" "NOME" \
  "New Oxford Modern English Teaching Guide 4" "English" "Grade 4" \
  "OUP Pakistan - New Oxford Modern English 3rd Ed Teacher Guide Grade 4"

process_book "$BASE/Teaching%20Guide%205.pdf" "NOME_TG5.pdf" "NOME" \
  "New Oxford Modern English Teaching Guide 5" "English" "Grade 5" \
  "OUP Pakistan - New Oxford Modern English 3rd Ed Teacher Guide Grade 5"

process_book "$BASE/Teaching%20Guide%206.pdf" "NOME_TG6.pdf" "NOME" \
  "New Oxford Modern English Teaching Guide 6" "English" "Grade 6" \
  "OUP Pakistan - New Oxford Modern English 3rd Ed Teacher Guide Grade 6"

process_book "$BASE/Teaching%20Guide%207.pdf" "NOME_TG7.pdf" "NOME" \
  "New Oxford Modern English Teaching Guide 7" "English" "Grade 7" \
  "OUP Pakistan - New Oxford Modern English 3rd Ed Teacher Guide Grade 7"

# ══════════════════════════════════════════
# NEW COUNTDOWN 3rd Edition (Maths)
# LSS Booklist: Grade 6–8
# ══════════════════════════════════════════
echo ""; echo "=============================="; echo "New Countdown 3rd Edition - Teacher Guides"; echo "=============================="

BASE="https://oup.com.pk/media/teaching-guides/New%20Countdown%203RD%20Edition"

process_book "$BASE/New%20Countdown%20TG-6%203rd%20Edition.pdf" "Countdown_TG6.pdf" "Countdown" \
  "New Countdown Teaching Guide 6" "Mathematics" "Grade 6" \
  "OUP Pakistan - New Countdown 3rd Edition Teacher Guide Grade 6"

process_book "$BASE/New%20Countdown%20TG-7%203rd%20Edition.pdf" "Countdown_TG7.pdf" "Countdown" \
  "New Countdown Teaching Guide 7" "Mathematics" "Grade 7" \
  "OUP Pakistan - New Countdown 3rd Edition Teacher Guide Grade 7"

process_book "$BASE/New%20Countdown%20TG-8%203rd%20Edition.pdf" "Countdown_TG8.pdf" "Countdown" \
  "New Countdown Teaching Guide 8" "Mathematics" "Grade 8" \
  "OUP Pakistan - New Countdown 3rd Edition Teacher Guide Grade 8"

# ══════════════════════════════════════════
# NEW OXFORD PRIMARY SCIENCE 3rd Edition
# LSS Booklist: Grade 1–5
# ══════════════════════════════════════════
echo ""; echo "=============================="; echo "New Oxford Primary Science - Teacher Guides"; echo "=============================="

BASE="https://oup.com.pk/media/teaching-guides/New%20Oxford%20Primary%20Science%203rd%20Edition"

process_book "$BASE/NOPS%20TG%201.pdf" "NOPS_TG1.pdf" "NOPS" \
  "New Oxford Primary Science Teaching Guide 1" "Science" "Grade 1" \
  "OUP Pakistan - New Oxford Primary Science 3rd Ed Teacher Guide Grade 1"

process_book "$BASE/NOPS%20TG%202.pdf" "NOPS_TG2.pdf" "NOPS" \
  "New Oxford Primary Science Teaching Guide 2" "Science" "Grade 2" \
  "OUP Pakistan - New Oxford Primary Science 3rd Ed Teacher Guide Grade 2"

process_book "$BASE/NOPS%20TG%203.pdf" "NOPS_TG3.pdf" "NOPS" \
  "New Oxford Primary Science Teaching Guide 3" "Science" "Grade 3" \
  "OUP Pakistan - New Oxford Primary Science 3rd Ed Teacher Guide Grade 3"

process_book "$BASE/NOPS%20TG%204.pdf" "NOPS_TG4.pdf" "NOPS" \
  "New Oxford Primary Science Teaching Guide 4" "Science" "Grade 4" \
  "OUP Pakistan - New Oxford Primary Science 3rd Ed Teacher Guide Grade 4"

process_book "$BASE/NOPS%20TG%205.pdf" "NOPS_TG5.pdf" "NOPS" \
  "New Oxford Primary Science Teaching Guide 5" "Science" "Grade 5" \
  "OUP Pakistan - New Oxford Primary Science 3rd Ed Teacher Guide Grade 5"

# ══════════════════════════════════════════
# KNOW YOUR WORLD (Social Studies/Geography)
# LSS Booklist: Grade 1–5
# ══════════════════════════════════════════
echo ""; echo "=============================="; echo "Know Your World - Teacher Guides"; echo "=============================="

BASE="https://oup.com.pk/media/teaching-guides/Know%20Your%20World"

process_book "$BASE/Know%20Your%20World%20TG%201.pdf" "KYW_TG1.pdf" "KYW" \
  "Know Your World Teaching Guide 1" "Social Studies" "Grade 1" \
  "OUP Pakistan - Know Your World Teacher Guide Grade 1"

process_book "$BASE/Know%20Your%20World%20TG%202.pdf" "KYW_TG2.pdf" "KYW" \
  "Know Your World Teaching Guide 2" "Social Studies" "Grade 2" \
  "OUP Pakistan - Know Your World Teacher Guide Grade 2"

process_book "$BASE/Know%20Your%20World%20TG%203.pdf" "KYW_TG3.pdf" "KYW" \
  "Know Your World Teaching Guide 3" "Social Studies" "Grade 3" \
  "OUP Pakistan - Know Your World Teacher Guide Grade 3"

process_book "$BASE/Know%20Your%20World%20TG%204.pdf" "KYW_TG4.pdf" "KYW" \
  "Know Your World Teaching Guide 4" "Social Studies" "Grade 4" \
  "OUP Pakistan - Know Your World Teacher Guide Grade 4"

process_book "$BASE/Know%20Your%20World%20TG%205.pdf" "KYW_TG5.pdf" "KYW" \
  "Know Your World Teaching Guide 5" "Social Studies" "Grade 5" \
  "OUP Pakistan - Know Your World Teacher Guide Grade 5"

# ══════════════════════════════════════════
# AMAZING SCIENCE
# LSS Booklist: Grade 6–7
# ══════════════════════════════════════════
echo ""; echo "=============================="; echo "Amazing Science - Teacher Guides"; echo "=============================="

BASE="https://oup.com.pk/media/teaching-guides/Amazing%20Science"

process_book "$BASE/Teaching%20Guide%206.pdf" "AmazingSci_TG6.pdf" "AmazingScience" \
  "Amazing Science Teaching Guide 6" "Science" "Grade 6" \
  "OUP Pakistan - Amazing Science Teacher Guide Grade 6"

process_book "$BASE/Teaching%20Guide%207.pdf" "AmazingSci_TG7.pdf" "AmazingScience" \
  "Amazing Science Teaching Guide 7" "Science" "Grade 7" \
  "OUP Pakistan - Amazing Science Teacher Guide Grade 7"

# ══════════════════════════════════════════
# HANDWRITING SKILLS BUILDER
# LSS Booklist: Grade 1–2
# ══════════════════════════════════════════
echo ""; echo "=============================="; echo "Handwriting Skills Builder"; echo "=============================="

BASE="https://oup.com.pk/media/teaching-guides/Handwriting%20Skills%20Builder"

process_book "$BASE/Handwriting-Skills-Builder-Grade-1.pdf" "HSB_Grade1.pdf" "Handwriting" \
  "Handwriting Skills Builder Grade 1" "English" "Grade 1" \
  "OUP Pakistan - Handwriting Skills Builder Grade 1"

process_book "$BASE/Handwriting-Skills-Builder-Grade-2.pdf" "HSB_Grade2.pdf" "Handwriting" \
  "Handwriting Skills Builder Grade 2" "English" "Grade 2" \
  "OUP Pakistan - Handwriting Skills Builder Grade 2"

# ══════════════════════════════════════════
# NEW SYLLABUS MATHEMATICS 7th Edition
# ══════════════════════════════════════════
echo ""; echo "=============================="; echo "New Syllabus Mathematics - Teacher Guides"; echo "=============================="

BASE="https://oup.com.pk/media/teaching-guides/New%20Syllabus%20Mathematics%207th%20Edition"

process_book "$BASE/NSM%20Teacher%27s%20Resource%20Book%201.pdf" "NSM_TRB1.pdf" "NSM" \
  "New Syllabus Mathematics Teacher Resource Book 1" "Mathematics" "Grade 6" \
  "OUP Pakistan - New Syllabus Mathematics 7th Ed Teacher Resource Book 1"

process_book "$BASE/NSM%20Teacher%27s%20Resource%20Book%202.pdf" "NSM_TRB2.pdf" "NSM" \
  "New Syllabus Mathematics Teacher Resource Book 2" "Mathematics" "Grade 7" \
  "OUP Pakistan - New Syllabus Mathematics 7th Ed Teacher Resource Book 2"

process_book "$BASE/NSM%20Teacher%27s%20Resource%20Book%203.pdf" "NSM_TRB3.pdf" "NSM" \
  "New Syllabus Mathematics Teacher Resource Book 3" "Mathematics" "Grade 8" \
  "OUP Pakistan - New Syllabus Mathematics 7th Ed Teacher Resource Book 3"

process_book "$BASE/NSM%20Teacher%27s%20Resource%20Book%204.pdf" "NSM_TRB4.pdf" "NSM" \
  "New Syllabus Mathematics Teacher Resource Book 4" "Mathematics" "Grade 9" \
  "OUP Pakistan - New Syllabus Mathematics 7th Ed Teacher Resource Book 4"

echo ""
echo "=============================="
echo "OUP Download Complete"
echo "=============================="
