require('dotenv').config({ override: true });
const express = require('express');
const cors = require('cors');
const helmet = require('helmet');
const morgan = require('morgan');
const rateLimit = require('express-rate-limit');
const path = require('path');
const { connectDB } = require('./config/database');
const routes = require('./routes');

const app = express();
const PORT = process.env.PORT || 5000;

// ─── SECURITY MIDDLEWARE ──────────────────────────────────────────────────────
app.use(helmet({ crossOriginResourcePolicy: { policy: 'cross-origin' } }));
app.use(cors({
  origin: [
    process.env.FRONTEND_URL || 'http://localhost:3001',
    'http://localhost:3000',
    'http://localhost:3001',
  ],
  credentials: true,
  methods: ['GET', 'POST', 'PUT', 'DELETE', 'PATCH'],
}));

// Rate limiting
const limiter = rateLimit({
  windowMs: parseInt(process.env.RATE_LIMIT_WINDOW_MS) || 15 * 60 * 1000,
  max: parseInt(process.env.RATE_LIMIT_MAX_REQUESTS) || 200,
  message: { error: 'Too many requests, please try again later' },
});
app.use('/api/', limiter);

// More lenient for chat (streaming)
const chatLimiter = rateLimit({ windowMs: 60 * 1000, max: 30 });
app.use('/api/chat/', chatLimiter);

// ─── BODY PARSING ─────────────────────────────────────────────────────────────
app.use(express.json({ limit: '10mb' }));
app.use(express.urlencoded({ extended: true, limit: '10mb' }));

// ─── LOGGING ─────────────────────────────────────────────────────────────────
if (process.env.NODE_ENV !== 'test') {
  app.use(morgan('dev'));
}

// ─── STATIC FILES ─────────────────────────────────────────────────────────────
app.use('/uploads', express.static(path.join(__dirname, '../uploads')));

// ─── HEALTH CHECK ─────────────────────────────────────────────────────────────
app.get('/health', (req, res) => {
  res.json({
    status: 'healthy',
    timestamp: new Date().toISOString(),
    school: process.env.SCHOOL_NAME || 'School AI Platform',
    version: '1.0.0',
  });
});

// ─── API ROUTES ───────────────────────────────────────────────────────────────
app.use('/api', routes);

// ─── 404 HANDLER ─────────────────────────────────────────────────────────────
app.use((req, res) => {
  res.status(404).json({ error: 'Route not found' });
});

// ─── ERROR HANDLER ────────────────────────────────────────────────────────────
app.use((err, req, res, next) => {
  console.error(err.stack);
  if (err.name === 'MulterError') {
    return res.status(400).json({ error: `File upload error: ${err.message}` });
  }
  res.status(err.status || 500).json({
    error: process.env.NODE_ENV === 'production' ? 'Internal server error' : err.message,
  });
});

// ─── START SERVER ─────────────────────────────────────────────────────────────
const startServer = async () => {
  await connectDB();

  // Create default admin user if not exists
  await createDefaultAdmin();

  app.listen(PORT, () => {
    console.log(`\n🚀 School AI Platform Backend`);
    console.log(`📡 Server: http://localhost:${PORT}`);
    console.log(`🏫 School: ${process.env.SCHOOL_NAME || 'School AI Platform'}`);
    console.log(`🌍 Environment: ${process.env.NODE_ENV || 'development'}\n`);
  });
};

const createDefaultAdmin = async () => {
  try {
    const bcrypt = require('bcryptjs');
    const { User } = require('./models');
    const existing = await User.findOne({ where: { login_id: 'admin001' } });
    if (!existing) {
      const hash = await bcrypt.hash('admin123', 12);
      await User.create({
        name: 'System Administrator',
        login_id: 'admin001',
        email: 'admin@school.edu',
        password_hash: hash,
        role: 'admin',
        is_active: true,
      });
      console.log('✅ Default admin created: admin001 / admin123');
      console.log('⚠️  IMPORTANT: Change the default admin password immediately!\n');
    }
  } catch (error) {
    console.error('Default admin creation error:', error.message);
  }
};

startServer();
