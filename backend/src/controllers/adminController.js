const bcrypt = require('bcryptjs');
const { User, Assignment, Submission, Document, ChatHistory, Notification } = require('../models');
const { sequelize } = require('../config/database');

// GET /api/admin/dashboard
const getDashboard = async (req, res) => {
  try {
    const [userStats] = await sequelize.query(`
      SELECT
        COUNT(*) as total_users,
        COUNT(CASE WHEN role = 'student' THEN 1 END) as students,
        COUNT(CASE WHEN role = 'teacher' THEN 1 END) as teachers,
        COUNT(CASE WHEN role = 'admin' THEN 1 END) as admins,
        COUNT(CASE WHEN is_active = false THEN 1 END) as inactive_users
      FROM users
    `, { type: sequelize.QueryTypes.SELECT });

    const [contentStats] = await sequelize.query(`
      SELECT
        (SELECT COUNT(*) FROM documents) as total_documents,
        (SELECT COUNT(*) FROM documents WHERE is_ingested = true) as ingested_docs,
        (SELECT COUNT(*) FROM document_chunks) as total_chunks,
        (SELECT COUNT(*) FROM assignments WHERE is_active = true) as active_assignments,
        (SELECT COUNT(*) FROM submissions WHERE status = 'submitted') as pending_submissions,
        (SELECT COUNT(*) FROM question_papers) as question_papers,
        (SELECT COUNT(*) FROM chat_history WHERE created_at > NOW() - INTERVAL '24 hours') as chats_today
    `, { type: sequelize.QueryTypes.SELECT });

    const recentActivity = await sequelize.query(`
      SELECT 'submission' as type, s.created_at, u.name as user_name, a.title as context
      FROM submissions s
      JOIN users u ON s.student_id = u.id
      JOIN assignments a ON s.assignment_id = a.id
      UNION ALL
      SELECT 'document' as type, d.created_at, u.name as user_name, d.title as context
      FROM documents d
      JOIN users u ON d.uploaded_by = u.id
      ORDER BY created_at DESC
      LIMIT 10
    `, { type: sequelize.QueryTypes.SELECT });

    res.json({
      users: userStats,
      content: contentStats,
      recent_activity: recentActivity,
    });
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch dashboard stats' });
  }
};

// GET /api/admin/users
const getUsers = async (req, res) => {
  try {
    const { role, is_active, search } = req.query;
    const where = {};
    if (role) where.role = role;
    if (is_active !== undefined) where.is_active = is_active === 'true';
    if (search) {
      const { Op } = require('sequelize');
      where[Op.or] = [
        { name: { [Op.iLike]: `%${search}%` } },
        { login_id: { [Op.iLike]: `%${search}%` } },
        { email: { [Op.iLike]: `%${search}%` } },
      ];
    }

    const users = await User.findAll({
      where,
      attributes: { exclude: ['password_hash'] },
      order: [['role', 'ASC'], ['name', 'ASC']],
    });

    res.json(users);
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch users' });
  }
};

// POST /api/admin/users
const createUser = async (req, res) => {
  try {
    const { name, login_id, email, password, role, class_name, subjects } = req.body;

    if (!name || !login_id || !password || !role) {
      return res.status(400).json({ error: 'Name, login ID, password, and role are required' });
    }

    // Check if login_id is unique
    const existing = await User.findOne({ where: { login_id } });
    if (existing) {
      return res.status(400).json({ error: 'Login ID already exists' });
    }

    const password_hash = await bcrypt.hash(password, 12);

    const user = await User.create({
      name,
      login_id,
      email: email || null,
      password_hash,
      role,
      class_name: class_name || null,
      subjects: subjects || [],
      is_active: true,
    });

    const { password_hash: _, ...userData } = user.toJSON();
    res.status(201).json(userData);
  } catch (error) {
    res.status(500).json({ error: 'Failed to create user' });
  }
};

// POST /api/admin/users/bulk (create multiple users at once)
const bulkCreateUsers = async (req, res) => {
  try {
    const { users } = req.body;
    if (!Array.isArray(users) || users.length === 0) {
      return res.status(400).json({ error: 'Users array is required' });
    }

    const results = { created: 0, failed: [], };
    for (const userData of users) {
      try {
        const { name, login_id, password, role, class_name, subjects } = userData;
        const existing = await User.findOne({ where: { login_id } });
        if (existing) {
          results.failed.push({ login_id, reason: 'Already exists' });
          continue;
        }
        const password_hash = await bcrypt.hash(password || login_id, 12);
        await User.create({ name, login_id, password_hash, role, class_name, subjects: subjects || [] });
        results.created++;
      } catch (err) {
        results.failed.push({ login_id: userData.login_id, reason: err.message });
      }
    }

    res.json(results);
  } catch (error) {
    res.status(500).json({ error: 'Bulk creation failed' });
  }
};

// PUT /api/admin/users/:id
const updateUser = async (req, res) => {
  try {
    const user = await User.findByPk(req.params.id);
    if (!user) return res.status(404).json({ error: 'User not found' });

    const { password, ...updateData } = req.body;
    if (password) {
      updateData.password_hash = await bcrypt.hash(password, 12);
    }

    await user.update(updateData);
    const { password_hash, ...userData } = user.toJSON();
    res.json(userData);
  } catch (error) {
    res.status(500).json({ error: 'Failed to update user' });
  }
};

// DELETE /api/admin/users/:id (soft delete)
const deleteUser = async (req, res) => {
  try {
    const user = await User.findByPk(req.params.id);
    if (!user) return res.status(404).json({ error: 'User not found' });
    if (user.id === req.user.id) return res.status(400).json({ error: 'Cannot delete own account' });

    await user.update({ is_active: false });
    res.json({ message: 'User deactivated' });
  } catch (error) {
    res.status(500).json({ error: 'Failed to delete user' });
  }
};

// POST /api/admin/broadcast (send notification to all)
const broadcastNotification = async (req, res) => {
  try {
    const { title, message, target_role } = req.body;
    if (!title || !message) {
      return res.status(400).json({ error: 'Title and message are required' });
    }

    const where = { is_active: true };
    if (target_role) where.role = target_role;

    const users = await User.findAll({ where, attributes: ['id'] });
    const notifications = users.map((u) => ({
      user_id: u.id,
      title,
      message,
      type: 'announcement',
    }));

    await Notification.bulkCreate(notifications);
    res.json({ message: `Notification sent to ${notifications.length} users` });
  } catch (error) {
    res.status(500).json({ error: 'Failed to send notification' });
  }
};

// GET /api/admin/notifications (for current user)
const getNotifications = async (req, res) => {
  try {
    const notifications = await Notification.findAll({
      where: { user_id: req.user.id },
      order: [['created_at', 'DESC']],
      limit: 50,
    });
    res.json(notifications);
  } catch (error) {
    res.status(500).json({ error: 'Failed to fetch notifications' });
  }
};

// PUT /api/admin/notifications/:id/read
const markNotificationRead = async (req, res) => {
  try {
    await Notification.update(
      { is_read: true },
      { where: { id: req.params.id, user_id: req.user.id } }
    );
    res.json({ message: 'Notification marked as read' });
  } catch (error) {
    res.status(500).json({ error: 'Failed to mark notification' });
  }
};

module.exports = { getDashboard, getUsers, createUser, bulkCreateUsers, updateUser, deleteUser, broadcastNotification, getNotifications, markNotificationRead };
