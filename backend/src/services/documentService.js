const fs = require('fs');
const path = require('path');
const { Document, DocumentChunk } = require('../models');
const { sequelize } = require('../config/database');

// ─── TEXT EXTRACTION ──────────────────────────────────────────────────────────

const extractTextFromPDF = async (filePath) => {
  const pdfParse = require('pdf-parse');
  const dataBuffer = fs.readFileSync(filePath);
  const data = await pdfParse(dataBuffer);
  return data.text;
};

const extractTextFromDOCX = async (filePath) => {
  const mammoth = require('mammoth');
  const result = await mammoth.extractRawText({ path: filePath });
  return result.value;
};

const extractTextFromTXT = (filePath) => {
  return fs.readFileSync(filePath, 'utf8');
};

const extractText = async (filePath, fileType) => {
  const ext = fileType.toLowerCase().replace('.', '');
  switch (ext) {
    case 'pdf':  return await extractTextFromPDF(filePath);
    case 'docx':
    case 'doc':  return await extractTextFromDOCX(filePath);
    case 'txt':  return extractTextFromTXT(filePath);
    default: throw new Error(`Unsupported file type: ${fileType}`);
  }
};

// ─── TEXT CHUNKING ────────────────────────────────────────────────────────────

const CHUNK_SIZE = 400;
const CHUNK_OVERLAP = 50;

const chunkText = (text) => {
  const cleaned = text
    .replace(/\r\n/g, '\n')
    .replace(/\n{3,}/g, '\n\n')
    .replace(/\s+/g, ' ')
    .trim();

  if (!cleaned) return [];

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
};

// ─── DOCUMENT INGESTION ───────────────────────────────────────────────────────

const isSQLite = sequelize.getDialect() === 'sqlite';

const ingestDocument = async (documentId) => {
  const doc = await Document.findByPk(documentId);
  if (!doc) throw new Error('Document not found');

  try {
    const rawText = await extractText(doc.file_path, doc.file_type);

    if (!rawText || rawText.trim().length < 50) {
      throw new Error('Could not extract meaningful text from document');
    }

    const chunks = chunkText(rawText);

    if (chunks.length === 0) {
      throw new Error('No valid text chunks could be created');
    }

    await DocumentChunk.destroy({ where: { document_id: documentId } });

    const chunkRecords = chunks.map((chunk) => ({
      document_id: documentId,
      chunk_text: chunk.text,
      chunk_index: chunk.index,
      word_count: chunk.wordCount,
    }));

    await DocumentChunk.bulkCreate(chunkRecords);

    // Update search vectors only on PostgreSQL
    if (!isSQLite) {
      await sequelize.query(`
        UPDATE document_chunks
        SET search_vector = to_tsvector('english', chunk_text)
        WHERE document_id = :docId
      `, { replacements: { docId: documentId } });
    }

    await doc.update({
      is_ingested: true,
      total_chunks: chunks.length,
      ingestion_error: null,
    });

    return { success: true, chunksCreated: chunks.length };
  } catch (error) {
    await doc.update({ is_ingested: false, ingestion_error: error.message });
    throw error;
  }
};

// ─── KNOWLEDGE BASE SEARCH ────────────────────────────────────────────────────

const searchKnowledgeBase = async (query, options = {}) => {
  const { subject = null, classLevel = null, limit = 8 } = options;

  try {
    if (isSQLite) {
      // SQLite: keyword search using LIKE
      const keywords = query.split(/\s+/).filter((w) => w.length > 2);
      if (keywords.length === 0) return [];

      const keywordConditions = keywords.map((_, i) => `dc.chunk_text LIKE :kw${i}`).join(' OR ');
      const replacements = { limit };
      keywords.forEach((kw, i) => { replacements[`kw${i}`] = `%${kw}%`; });

      let documentFilter = '';
      if (subject) {
        documentFilter += ` AND d.subject LIKE :subject`;
        replacements.subject = `%${subject}%`;
      }
      if (classLevel) {
        documentFilter += ` AND (d.class_level LIKE :classLevel OR d.class_level = 'All Classes')`;
        replacements.classLevel = `%${classLevel}%`;
      }

      return await sequelize.query(`
        SELECT
          dc.id, dc.chunk_text, dc.chunk_index,
          d.title AS document_title, d.subject, d.class_level,
          0.5 AS rank
        FROM document_chunks dc
        JOIN documents d ON dc.document_id = d.id
        WHERE d.is_ingested = 1 AND (${keywordConditions}) ${documentFilter}
        ORDER BY d.created_at DESC
        LIMIT :limit
      `, { replacements, type: sequelize.QueryTypes.SELECT });
    }

    // PostgreSQL: full-text search
    let documentFilter = '';
    const replacements = { query, limit };

    if (subject) {
      documentFilter += ` AND d.subject ILIKE :subject`;
      replacements.subject = `%${subject}%`;
    }
    if (classLevel) {
      documentFilter += ` AND (d.class_level ILIKE :classLevel OR d.class_level = 'All Classes')`;
      replacements.classLevel = `%${classLevel}%`;
    }

    const results = await sequelize.query(`
      SELECT
        dc.id, dc.chunk_text, dc.chunk_index,
        d.title AS document_title, d.subject, d.class_level,
        ts_rank(dc.search_vector, plainto_tsquery('english', :query)) AS rank
      FROM document_chunks dc
      JOIN documents d ON dc.document_id = d.id
      WHERE
        d.is_ingested = true
        AND dc.search_vector @@ plainto_tsquery('english', :query)
        ${documentFilter}
      ORDER BY rank DESC
      LIMIT :limit
    `, { replacements, type: sequelize.QueryTypes.SELECT });

    if (results.length === 0) {
      const keywords = query.split(/\s+/).filter((w) => w.length > 3);
      if (keywords.length > 0) {
        const keywordConditions = keywords.map((_, i) => `dc.chunk_text ILIKE :kw${i}`).join(' OR ');
        const kwReplacements = { limit };
        keywords.forEach((kw, i) => { kwReplacements[`kw${i}`] = `%${kw}%`; });
        if (subject) kwReplacements.subject = `%${subject}%`;
        if (classLevel) kwReplacements.classLevel = `%${classLevel}%`;

        return await sequelize.query(`
          SELECT dc.id, dc.chunk_text, dc.chunk_index,
            d.title AS document_title, d.subject, d.class_level, 0.1 AS rank
          FROM document_chunks dc
          JOIN documents d ON dc.document_id = d.id
          WHERE d.is_ingested = true AND (${keywordConditions}) ${documentFilter}
          ORDER BY d.created_at DESC
          LIMIT :limit
        `, { replacements: kwReplacements, type: sequelize.QueryTypes.SELECT });
      }
    }

    return results;
  } catch (error) {
    console.error('Knowledge base search error:', error);
    return [];
  }
};

// ─── BUILD CONTEXT STRING ─────────────────────────────────────────────────────

const buildContext = (searchResults) => {
  if (!searchResults || searchResults.length === 0) return null;

  return searchResults.map((result, i) =>
    `[Source ${i + 1}: "${result.document_title}" (${result.subject} - ${result.class_level})]\n${result.chunk_text}`
  ).join('\n\n---\n\n');
};

module.exports = { ingestDocument, searchKnowledgeBase, buildContext };
