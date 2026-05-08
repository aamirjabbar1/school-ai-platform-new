/**
 * OCR Script for LSS Chat Knowledge Base
 * Uses pdfjs-dist to render PDF pages + Claude Vision API to extract text
 *
 * Run with: node ocr_pdfs.mjs
 */

import * as pdfjsLib from '../backend/node_modules/pdfjs-dist/legacy/build/pdf.mjs';
import { createRequire } from 'module';
const require = createRequire(import.meta.url);
const { createCanvas } = require('../backend/node_modules/@napi-rs/canvas');
import Anthropic from '../backend/node_modules/@anthropic-ai/sdk/index.js';
import Database from '../backend/node_modules/better-sqlite3/lib/index.js';
import { readFileSync, readdirSync, existsSync, writeFileSync } from 'fs';
import { join, resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const BACKEND_DIR = resolve(__dirname, '../backend');
const UPLOADS_DIR = join(BACKEND_DIR, 'uploads/documents');
const DB_PATH = join(BACKEND_DIR, 'school_ai.sqlite');

// ─── CONFIG ───────────────────────────────────────────────────────────────────

const ANTHROPIC_API_KEY = process.env.ANTHROPIC_API_KEY;
const RENDER_SCALE = 2.0;       // Higher = better OCR quality but more API tokens
const MAX_PAGES = 200;          // Max pages to OCR per document
const PAGES_PER_BATCH = 3;      // Send 3 pages per Claude API call
const CHUNK_SIZE = 400;         // words per chunk
const CHUNK_OVERLAP = 50;       // word overlap

if (!ANTHROPIC_API_KEY || ANTHROPIC_API_KEY === 'your_anthropic_api_key_here') {
  console.error('ERROR: ANTHROPIC_API_KEY not set. Please set it in backend/.env');
  process.exit(1);
}

const client = new Anthropic({ apiKey: ANTHROPIC_API_KEY });

// ─── DATABASE ─────────────────────────────────────────────────────────────────

const db = new Database(DB_PATH);

function getUningestedDocs() {
  return db.prepare(`
    SELECT id, title, file_path, file_type, subject, class_level
    FROM documents
    WHERE is_ingested = 0 OR is_ingested = false
    ORDER BY created_at ASC
  `).all();
}

function insertChunks(docId, chunks) {
  const insert = db.prepare(`
    INSERT INTO document_chunks (id, document_id, chunk_text, chunk_index, word_count, created_at, updated_at)
    VALUES (lower(hex(randomblob(16))), ?, ?, ?, ?, datetime('now'), datetime('now'))
  `);

  const deleteOld = db.prepare('DELETE FROM document_chunks WHERE document_id = ?');
  const updateDoc = db.prepare(`
    UPDATE documents
    SET is_ingested = 1, total_chunks = ?, ingestion_error = NULL, updated_at = datetime('now')
    WHERE id = ?
  `);

  const insertMany = db.transaction((chunks) => {
    deleteOld.run(docId);
    for (const chunk of chunks) {
      insert.run(docId, chunk.text, chunk.index, chunk.wordCount);
    }
    updateDoc.run(chunks.length, docId);
  });

  insertMany(chunks);
}

function markError(docId, error) {
  db.prepare(`
    UPDATE documents
    SET ingestion_error = ?, updated_at = datetime('now')
    WHERE id = ?
  `).run(error.substring(0, 500), docId);
}

// ─── PDF RENDERING ────────────────────────────────────────────────────────────

async function renderPageToBase64(page) {
  const viewport = page.getViewport({ scale: RENDER_SCALE });
  const canvas = createCanvas(Math.floor(viewport.width), Math.floor(viewport.height));
  const ctx = canvas.getContext('2d');

  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  await page.render({
    canvasContext: ctx,
    viewport,
  }).promise;

  const buffer = canvas.toBuffer('image/jpeg', { quality: 0.85 });
  return buffer.toString('base64');
}

// ─── OCR VIA CLAUDE VISION ────────────────────────────────────────────────────

async function ocrPageBatch(base64Images, pageNums) {
  const content = [];

  for (let i = 0; i < base64Images.length; i++) {
    content.push({
      type: 'text',
      text: `--- Page ${pageNums[i]} ---`,
    });
    content.push({
      type: 'image',
      source: {
        type: 'base64',
        media_type: 'image/jpeg',
        data: base64Images[i],
      },
    });
  }

  content.push({
    type: 'text',
    text: `Please extract ALL text from the textbook page(s) above.
Rules:
- Extract every word of text visible in the images
- Preserve paragraph breaks with blank lines
- For tables, use | to separate columns
- Include headers, chapter titles, exercise numbers
- For mixed Urdu/English, transcribe both languages
- Do NOT summarize or skip any content
- Output only the extracted text, nothing else`,
  });

  const response = await client.messages.create({
    model: 'claude-haiku-4-5-20251001',
    max_tokens: 4096,
    messages: [{ role: 'user', content }],
  });

  return response.content[0]?.text || '';
}

// ─── TEXT CHUNKING ────────────────────────────────────────────────────────────

function chunkText(text) {
  const cleaned = text
    .replace(/\r\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/\s+/g, ' ')
    .trim();

  if (!cleaned || cleaned.length < 50) return [];

  const words = cleaned.split(/\s+/);
  const chunks = [];
  let i = 0;

  while (i < words.length) {
    const end = Math.min(i + CHUNK_SIZE, words.length);
    const chunk = words.slice(i, end).join(' ');
    if (chunk.trim().length > 50) {
      chunks.push({ text: chunk.trim(), wordCount: end - i, index: chunks.length });
    }
    i += CHUNK_SIZE - CHUNK_OVERLAP;
  }

  return chunks;
}

// ─── MAIN OCR FUNCTION ────────────────────────────────────────────────────────

async function processPDF(doc) {
  console.log(`\nProcessing: ${doc.title}`);

  // Resolve file path relative to backend dir if it's relative
  const filePath = doc.file_path.startsWith('/') || /^[A-Za-z]:/.test(doc.file_path)
    ? doc.file_path
    : join(BACKEND_DIR, doc.file_path);

  console.log(`  File: ${filePath}`);

  if (!existsSync(filePath)) {
    console.log(`  ERROR: File not found: ${filePath}`);
    markError(doc.id, `File not found: ${filePath}`);
    return false;
  }

  // Load PDF
  const data = new Uint8Array(readFileSync(filePath));
  const pdfDoc = await pdfjsLib.getDocument({
    data,
    cMapUrl: join(BACKEND_DIR, 'node_modules/pdfjs-dist/cmaps').replace(/\\/g, '/') + '/',
    cMapPacked: true,
    standardFontDataUrl: join(BACKEND_DIR, 'node_modules/pdfjs-dist/standard_fonts').replace(/\\/g, '/') + '/',
  }).promise;

  const numPages = Math.min(pdfDoc.numPages, MAX_PAGES);
  console.log(`  Pages to process: ${numPages} of ${pdfDoc.numPages}`);

  // First, try pdf-parse for text-based PDFs
  let allText = '';

  // Render and OCR pages in batches
  let pagesProcessed = 0;

  for (let i = 0; i < numPages; i += PAGES_PER_BATCH) {
    const batchEnd = Math.min(i + PAGES_PER_BATCH, numPages);
    const batch = [];
    const pageNums = [];

    for (let j = i; j < batchEnd; j++) {
      const page = await pdfDoc.getPage(j + 1);
      const base64 = await renderPageToBase64(page);
      batch.push(base64);
      pageNums.push(j + 1);
    }

    process.stdout.write(`  Batch ${Math.floor(i/PAGES_PER_BATCH)+1}/${Math.ceil(numPages/PAGES_PER_BATCH)} (pages ${pageNums[0]}-${pageNums[pageNums.length-1]})...`);

    try {
      const text = await ocrPageBatch(batch, pageNums);
      allText += text + '\n\n';
      pagesProcessed += batch.length;
      process.stdout.write(` ${text.split(/\s+/).length} words\n`);
    } catch (err) {
      process.stdout.write(` ERROR: ${err.message}\n`);
      // Continue with next batch
      await new Promise(r => setTimeout(r, 2000));
    }

    // Small delay between batches to respect rate limits
    if (i + PAGES_PER_BATCH < numPages) {
      await new Promise(r => setTimeout(r, 500));
    }
  }

  if (allText.trim().length < 100) {
    console.log(`  ERROR: No meaningful text extracted`);
    markError(doc.id, 'OCR produced no meaningful text');
    return false;
  }

  // Save extracted text for debugging/caching
  const txtPath = filePath.replace(/\.pdf$/i, '_ocr.txt');
  writeFileSync(txtPath, allText, 'utf8');

  // Chunk and insert
  const chunks = chunkText(allText);
  console.log(`  Creating ${chunks.length} chunks from ${allText.split(/\s+/).length} words...`);

  insertChunks(doc.id, chunks);

  console.log(`  Done! ${chunks.length} chunks inserted.`);
  return true;
}

// ─── ENTRY POINT ──────────────────────────────────────────────────────────────

async function main() {
  console.log('='.repeat(60));
  console.log('LSS Chat Knowledge Base - OCR Processing');
  console.log('='.repeat(60));

  const docs = getUningestedDocs();

  if (docs.length === 0) {
    console.log('No unprocessed documents found.');
    db.close();
    return;
  }

  console.log(`Found ${docs.length} document(s) to process:`);
  docs.forEach(d => console.log(`  - ${d.title}`));

  let success = 0, failed = 0;

  for (const doc of docs) {
    if (doc.file_type !== 'pdf') {
      console.log(`\nSkipping non-PDF: ${doc.title}`);
      continue;
    }

    try {
      const ok = await processPDF(doc);
      if (ok) success++;
      else failed++;
    } catch (err) {
      console.error(`\nFailed: ${doc.title}:`, err.message);
      markError(doc.id, err.message);
      failed++;
    }
  }

  db.close();

  console.log('\n' + '='.repeat(60));
  console.log(`OCR Complete: ${success} succeeded, ${failed} failed`);
  console.log('='.repeat(60));
}

main().catch(err => {
  console.error('Fatal error:', err);
  process.exit(1);
});
