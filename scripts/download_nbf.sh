#!/bin/bash
# NBF Books Download & Upload Script

API="http://localhost:5000/api"
DOWNDIR="$(dirname "$0")/../backend/knowledge_base_downloads"

# Get JWT token
echo "Logging in..."
TOKEN=$(curl -s -X POST "$API/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"login_id":"admin001","password":"admin123"}' | python -c "import sys,json; print(json.load(sys.stdin)['token'])")

if [ -z "$TOKEN" ]; then
  echo "ERROR: Login failed"
  exit 1
fi
echo "Login OK"

mkdir -p "$DOWNDIR/NBF/Grade9"
mkdir -p "$DOWNDIR/NBF/Grade10"

# ──────────────────────────────────────────
# Helper: download + upload one book
# Usage: process_book <url> <filename> <dest_subdir> <title> <subject> <class_level> <description>
# ──────────────────────────────────────────
process_book() {
  local URL="$1"
  local FNAME="$2"
  local SUBDIR="$3"
  local TITLE="$4"
  local SUBJECT="$5"
  local CLASS="$6"
  local DESC="$7"
  local DEST="$DOWNDIR/NBF/$SUBDIR/$FNAME"

  echo ""
  echo "==> $TITLE"

  # Download if not already present
  if [ -f "$DEST" ]; then
    SIZE=$(du -k "$DEST" | cut -f1)
    echo "  Already downloaded (${SIZE}KB)"
  else
    echo "  Downloading from $URL"
    curl -s -L -k --max-time 120 -o "$DEST" "$URL"
    if [ $? -eq 0 ] && [ -f "$DEST" ]; then
      SIZE=$(du -k "$DEST" | cut -f1)
      if [ "$SIZE" -lt 5 ]; then
        echo "  SKIP: File too small (${SIZE}KB) - probably not a real PDF"
        rm -f "$DEST"
        return
      fi
      echo "  Downloaded OK (${SIZE}KB)"
    else
      echo "  FAILED to download"
      return
    fi
  fi

  # Upload to knowledge base
  echo "  Uploading to knowledge base..."
  RESULT=$(curl -s -X POST "$API/documents/upload" \
    -H "Authorization: Bearer $TOKEN" \
    -F "document=@$DEST;type=application/pdf" \
    -F "title=$TITLE" \
    -F "subject=$SUBJECT" \
    -F "class_level=$CLASS" \
    -F "description=$DESC")

  ID=$(echo "$RESULT" | python -c "import sys,json; d=json.load(sys.stdin); print(d.get('id','ERR'))" 2>/dev/null)
  if [ "$ID" != "ERR" ] && [ -n "$ID" ]; then
    echo "  Uploaded OK (ID: $ID)"
  else
    echo "  Upload result: $RESULT"
  fi
}

# ──────────────────────────────────────────
# NBF GRADE 9
# ──────────────────────────────────────────
echo ""
echo "=============================="
echo "NBF Grade 9 Books"
echo "=============================="

process_book \
  "https://www.nbf.org.pk/sites/default/files/Computer%20Grade%209-1.pdf" \
  "NBF_ComputerScience_Grade9.pdf" \
  "Grade9" \
  "NBF Computer Science Grade 9" \
  "Computer Science" \
  "Grade 9" \
  "National Book Foundation - Computer Science Grade 9"

process_book \
  "https://www.nbf.org.pk/sites/default/files/General%20Science%209.pdf" \
  "NBF_GeneralScience_Grade9.pdf" \
  "Grade9" \
  "NBF General Science Grade 9" \
  "Science" \
  "Grade 9" \
  "National Book Foundation - General Science Grade 9"

process_book \
  "https://www.nbf.org.pk/sites/default/files/Economic%209_0.pdf" \
  "NBF_Economics_Grade9.pdf" \
  "Grade9" \
  "NBF Economics Grade 9" \
  "Economics" \
  "Grade 9" \
  "National Book Foundation - Economics Grade 9"

process_book \
  "https://www.nbf.org.pk/sites/default/files/English%209.pdf" \
  "NBF_English_Grade9.pdf" \
  "Grade9" \
  "NBF English Grade 9" \
  "English" \
  "Grade 9" \
  "National Book Foundation - English Grade 9"

process_book \
  "https://www.nbf.org.pk/sites/default/files/Urdu%209.pdf" \
  "NBF_Urdu_Grade9.pdf" \
  "Grade9" \
  "NBF Urdu Grade 9" \
  "Urdu" \
  "Grade 9" \
  "National Book Foundation - Urdu Grade 9"

process_book \
  "https://www.nbf.org.pk/sites/default/files/Physics%209.pdf" \
  "NBF_Physics_Grade9.pdf" \
  "Grade9" \
  "NBF Physics Grade 9" \
  "Physics" \
  "Grade 9" \
  "National Book Foundation - Physics Grade 9"

process_book \
  "https://www.nbf.org.pk/sites/default/files/Chemistry%209.pdf" \
  "NBF_Chemistry_Grade9.pdf" \
  "Grade9" \
  "NBF Chemistry Grade 9" \
  "Chemistry" \
  "Grade 9" \
  "National Book Foundation - Chemistry Grade 9"

process_book \
  "https://www.nbf.org.pk/sites/default/files/Biology%209.pdf" \
  "NBF_Biology_Grade9.pdf" \
  "Grade9" \
  "NBF Biology Grade 9" \
  "Biology" \
  "Grade 9" \
  "National Book Foundation - Biology Grade 9"

process_book \
  "https://www.nbf.org.pk/sites/default/files/Mathematics%209.pdf" \
  "NBF_Mathematics_Grade9.pdf" \
  "Grade9" \
  "NBF Mathematics Grade 9" \
  "Mathematics" \
  "Grade 9" \
  "National Book Foundation - Mathematics Grade 9"

process_book \
  "https://www.nbf.org.pk/sites/default/files/Pakistan%20Studies%209.pdf" \
  "NBF_PakistanStudies_Grade9.pdf" \
  "Grade9" \
  "NBF Pakistan Studies Grade 9" \
  "Pakistan Studies" \
  "Grade 9" \
  "National Book Foundation - Pakistan Studies Grade 9"

# ──────────────────────────────────────────
# NBF GRADE 10
# ──────────────────────────────────────────
echo ""
echo "=============================="
echo "NBF Grade 10 Books"
echo "=============================="

process_book \
  "https://www.nbf.org.pk/sites/default/files/English%2010.pdf" \
  "NBF_English_Grade10.pdf" \
  "Grade10" \
  "NBF English Grade 10" \
  "English" \
  "Grade 10" \
  "National Book Foundation - English Grade 10"

process_book \
  "https://www.nbf.org.pk/sites/default/files/Physics%2010.pdf" \
  "NBF_Physics_Grade10.pdf" \
  "Grade10" \
  "NBF Physics Grade 10" \
  "Physics" \
  "Grade 10" \
  "National Book Foundation - Physics Grade 10"

process_book \
  "https://www.nbf.org.pk/sites/default/files/Chemistry%2010.pdf" \
  "NBF_Chemistry_Grade10.pdf" \
  "Grade10" \
  "NBF Chemistry Grade 10" \
  "Chemistry" \
  "Grade 10" \
  "National Book Foundation - Chemistry Grade 10"

process_book \
  "https://www.nbf.org.pk/sites/default/files/Biology%2010.pdf" \
  "NBF_Biology_Grade10.pdf" \
  "Grade10" \
  "NBF Biology Grade 10" \
  "Biology" \
  "Grade 10" \
  "National Book Foundation - Biology Grade 10"

process_book \
  "https://www.nbf.org.pk/sites/default/files/Mathematics%2010.pdf" \
  "NBF_Mathematics_Grade10.pdf" \
  "Grade10" \
  "NBF Mathematics Grade 10" \
  "Mathematics" \
  "Grade 10" \
  "National Book Foundation - Mathematics Grade 10"

process_book \
  "https://www.nbf.org.pk/sites/default/files/Computer%20Grade%2010.pdf" \
  "NBF_ComputerScience_Grade10.pdf" \
  "Grade10" \
  "NBF Computer Science Grade 10" \
  "Computer Science" \
  "Grade 10" \
  "National Book Foundation - Computer Science Grade 10"

process_book \
  "https://www.nbf.org.pk/sites/default/files/Urdu%2010.pdf" \
  "NBF_Urdu_Grade10.pdf" \
  "Grade10" \
  "NBF Urdu Grade 10" \
  "Urdu" \
  "Grade 10" \
  "National Book Foundation - Urdu Grade 10"

process_book \
  "https://www.nbf.org.pk/sites/default/files/Pakistan%20Studies%2010.pdf" \
  "NBF_PakistanStudies_Grade10.pdf" \
  "Grade10" \
  "NBF Pakistan Studies Grade 10" \
  "Pakistan Studies" \
  "Grade 10" \
  "National Book Foundation - Pakistan Studies Grade 10"

process_book \
  "https://www.nbf.org.pk/sites/default/files/Islamiat%2010.pdf" \
  "NBF_Islamiat_Grade10.pdf" \
  "Grade10" \
  "NBF Islamiat Grade 10" \
  "Islamiat" \
  "Grade 10" \
  "National Book Foundation - Islamiat Grade 10"

echo ""
echo "=============================="
echo "All done!"
echo "=============================="
