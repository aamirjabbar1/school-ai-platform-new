const path = require('path');
const { Document, DocumentChunk } = require('../models');
const { ingestDocument } = require('../services/documentService');

// GET /api/documents
const getDocuments = async (req, res) => {
  try {
    const { subject, class_level } = req.query;
    const where = {};
    if (subject) where.subject = subject;
    if (class_level) where.class_level = class_level;

    const documents = await Document.findAll({
      where,
      attributes: { exclude: ['file_path'] }, // Don't expose file paths
      order: [['created_at', 'DESC']],
    });

    res.json(documents);
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch documents' });
  }
};

// POST /api/documents/upload (admin/teacher only)
const uploadDocument = async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: 'No file uploaded' });
    }

    const { title, subject, class_level, description } = req.body;
    if (!title || !subject || !class_level) {
      return res.status(400).json({ error: 'Title, subject, and class level are required' });
    }

    const ext = path.extname(req.file.originalname).toLowerCase().slice(1);

    const doc = await Document.create({
      title,
      subject,
      class_level,
      description: description || null,
      file_path: req.file.path,
      file_name: req.file.originalname,
      file_type: ext,
      file_size: req.file.size,
      uploaded_by: req.user.id,
      is_ingested: false,
    });

    // Start background ingestion
    ingestDocument(doc.id)
      .then((result) => {
        console.log(`✅ Document "${title}" ingested: ${result.chunksCreated} chunks`);
      })
      .catch((err) => {
        console.error(`❌ Document ingestion failed for "${title}":`, err.message);
      });

    res.status(201).json({
      ...doc.toJSON(),
      file_path: undefined,
      message: 'Document uploaded. Ingestion is in progress.',
    });
  } catch (error) {
    res.status(500).json({ error: 'Failed to upload document' });
  }
};

// POST /api/documents/:id/reingest (admin only)
const reingestDocument = async (req, res) => {
  try {
    const doc = await Document.findByPk(req.params.id);
    if (!doc) return res.status(404).json({ error: 'Document not found' });

    await doc.update({ is_ingested: false, total_chunks: 0, ingestion_error: null });

    ingestDocument(doc.id)
      .then((result) => {
        console.log(`✅ Re-ingestion completed for "${doc.title}": ${result.chunksCreated} chunks`);
      })
      .catch((err) => {
        console.error(`❌ Re-ingestion failed for "${doc.title}":`, err.message);
      });

    res.json({ message: 'Re-ingestion started' });
  } catch (error) {
    res.status(500).json({ error: 'Failed to start re-ingestion' });
  }
};

// DELETE /api/documents/:id (admin only)
const deleteDocument = async (req, res) => {
  try {
    const doc = await Document.findByPk(req.params.id);
    if (!doc) return res.status(404).json({ error: 'Document not found' });

    // Delete chunks first (cascade should handle this, but being explicit)
    await DocumentChunk.destroy({ where: { document_id: doc.id } });
    await doc.destroy();

    res.json({ message: 'Document deleted' });
  } catch (error) {
    res.status(500).json({ error: 'Failed to delete document' });
  }
};

// GET /api/documents/stats (admin only)
const getStats = async (req, res) => {
  try {
    const { sequelize } = require('../config/database');
    const stats = await sequelize.query(`
      SELECT
        COUNT(DISTINCT d.id) as total_documents,
        COUNT(DISTINCT CASE WHEN d.is_ingested = true THEN d.id END) as ingested_documents,
        COUNT(DISTINCT dc.id) as total_chunks,
        COUNT(DISTINCT d.subject) as subjects_covered,
        COUNT(DISTINCT d.class_level) as class_levels
      FROM documents d
      LEFT JOIN document_chunks dc ON dc.document_id = d.id
    `, { type: sequelize.QueryTypes.SELECT });

    const bySubject = await sequelize.query(`
      SELECT subject, COUNT(*) as count, SUM(total_chunks) as chunks
      FROM documents
      WHERE is_ingested = true
      GROUP BY subject
      ORDER BY count DESC
    `, { type: sequelize.QueryTypes.SELECT });

    res.json({ ...stats[0], by_subject: bySubject });
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch stats' });
  }
};

module.exports = { getDocuments, uploadDocument, reingestDocument, deleteDocument, getStats };
