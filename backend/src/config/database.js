const { Sequelize } = require('sequelize');
const path = require('path');
require('dotenv').config();

const isPostgres = process.env.DB_DIALECT === 'postgres' ||
  (process.env.DB_HOST && process.env.DB_HOST !== 'localhost' && process.env.NODE_ENV === 'production');

let sequelize;

if (isPostgres) {
  sequelize = new Sequelize(
    process.env.DB_NAME || 'school_ai_db',
    process.env.DB_USER || 'postgres',
    process.env.DB_PASSWORD || 'password',
    {
      host: process.env.DB_HOST || 'localhost',
      port: parseInt(process.env.DB_PORT) || 5432,
      dialect: 'postgres',
      logging: false,
      pool: { max: 10, min: 0, acquire: 30000, idle: 10000 },
    }
  );
} else {
  // SQLite for local development — no separate DB server needed
  sequelize = new Sequelize({
    dialect: 'sqlite',
    storage: path.join(__dirname, '../../school_ai.sqlite'),
    logging: false,
  });
}

const connectDB = async () => {
  try {
    await sequelize.authenticate();
    console.log(`✅ Database connected (${isPostgres ? 'PostgreSQL' : 'SQLite'}).`);
    await sequelize.sync({ alter: false });
    console.log('✅ Database models synchronized.');
    if (isPostgres) await setupFullTextSearch();
  } catch (error) {
    console.error('❌ Database connection error:', error);
    process.exit(1);
  }
};

const setupFullTextSearch = async () => {
  try {
    await sequelize.query(`
      DO $$ BEGIN
        ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS search_vector tsvector;
      EXCEPTION WHEN duplicate_column THEN NULL;
      END $$;
    `);
    await sequelize.query(`
      CREATE INDEX IF NOT EXISTS idx_document_chunks_search
      ON document_chunks USING GIN(search_vector);
    `);
    await sequelize.query(`
      CREATE OR REPLACE FUNCTION update_document_chunk_search_vector()
      RETURNS TRIGGER AS $$
      BEGIN
        NEW.search_vector := to_tsvector('english', COALESCE(NEW.chunk_text, ''));
        RETURN NEW;
      END;
      $$ LANGUAGE plpgsql;
    `);
    await sequelize.query(`
      DROP TRIGGER IF EXISTS document_chunks_search_vector_update ON document_chunks;
      CREATE TRIGGER document_chunks_search_vector_update
        BEFORE INSERT OR UPDATE ON document_chunks
        FOR EACH ROW EXECUTE FUNCTION update_document_chunk_search_vector();
    `);
    console.log('✅ Full-text search configured.');
  } catch (error) {
    console.log('ℹ️  Full-text search setup (non-fatal):', error.message);
  }
};

module.exports = { sequelize, connectDB };
