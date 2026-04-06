# LANHub Documentation Index

**Quick reference guide for all LANHub documentation**

---

## 📖 Start Here

### New to LANHub?
Start with these in order:

1. **[README.md](README.md)** (5 min read)
   - Project overview
   - Installation instructions
   - Project goals

2. **[DEVELOPER_GUIDE.md#repository-architecture](DEVELOPER_GUIDE.md#repository-architecture)** (10 min read)
   - How the app is structured
   - Component relationships
   - Request flow diagrams

3. **[ORGANIZATION.md](ORGANIZATION.md)** (5 min read)
   - Complete directory structure
   - File descriptions
   - What goes where

---

## 🎯 Common Tasks

### "I want to add a new feature"
→ Read: **[DEVELOPER_GUIDE.md#how-to-add-a-new-feature](DEVELOPER_GUIDE.md#how-to-add-a-new-feature)** (30 min)

Complete step-by-step guide including:
- Planning the feature
- Database changes
- Business logic (functions/)
- API endpoints (blueprints/)
- Socket handlers (socket_events/)
- Frontend (templates/)
- Testing

### "I want to add a new game"
→ Read: **[DEVELOPER_GUIDE.md#task-1-add-a-new-game](DEVELOPER_GUIDE.md#task-1-add-a-new-game)** (15 min)

Minimal example with:
- Blueprint file
- Socket events
- Template integration
- App registration

### "I want to add an admin feature"
→ Read: **[DEVELOPER_GUIDE.md#task-2-add-admin-feature](DEVELOPER_GUIDE.md#task-2-add-admin-feature)** (15 min)

Example showing:
- Admin authentication
- REST endpoints
- Admin-only routes

### "I need to query the database"
→ Read: **[DEVELOPER_GUIDE.md#database-operations](DEVELOPER_GUIDE.md#database-operations)** (10 min)

Covers:
- All database functions
- Query patterns
- Performance tips
- SQL examples

### "I'm debugging an issue"
→ Read: **[DEVELOPER_GUIDE.md#debugging--troubleshooting](DEVELOPER_GUIDE.md#debugging--troubleshooting)** (10 min)

Includes:
- Enabling debug mode
- Checking logs
- Common issues & solutions
- Testing utilities

---

## 💾 Core Module Documentation

All functions documented with usage examples in:
**[DEVELOPER_GUIDE.md#core-python-modules](DEVELOPER_GUIDE.md#core-python-modules)**

### Database (⭐ Most Used)
**[DEVELOPER_GUIDE.md#1-functionsdbpy](DEVELOPER_GUIDE.md#1-functionsdbpy)** 

Functions:
- `get_db()` - Get database connection
- `db_query()` - SELECT queries
- `db_get_row()` - Get single row
- `db_insert()` - Add new row
- `db_update_row()` - Update row
- `db_delete_row()` - Delete row

### Chat & Messaging
**[DEVELOPER_GUIDE.md#2-functionschatpy](DEVELOPER_GUIDE.md#2-functionschatpy)**

Functions:
- `save_chat_message()` - Save direct message
- `create_channel()` - Create chat channel
- `save_channel_message()` - Post to channel
- `is_rate_limited()` - Check message rate limit
- `verify_channel_password()` - Authenticate channel

### Session Management
**[DEVELOPER_GUIDE.md#3-sharedgame_sessionpy](DEVELOPER_GUIDE.md#3-sharedgame_sessionpy)**

Usage:
- Create: `GameSessionManager(name="chess")`
- Get: `sessions[request.sid]` 
- Check: `request.sid in sessions`
- List: `sessions.get_active_usernames()`

### Input Validation
**[DEVELOPER_GUIDE.md#4-sharedvalidatorspy](DEVELOPER_GUIDE.md#4-sharedvalidatorspy)**

Functions:
- `validate_username()` - Check username valid
- `validate_message()` - Check message valid
- `validate_email()` - Check email format

### Admin Management
**[DEVELOPER_GUIDE.md#5-functionsadminpy](DEVELOPER_GUIDE.md#5-functionsadminpy)**

Functions:
- `get_all_admins()` - List all admins
- `create_admin()` - Add new admin
- `delete_admin()` - Remove admin

### Server Monitoring
**[DEVELOPER_GUIDE.md#6-functionsserverpy](DEVELOPER_GUIDE.md#6-functionsserverpy)**

Functions:
- `get_server_stats()` - CPU, RAM, disk usage
- `get_full_server_stats()` - Comprehensive stats
- `get_uptime_seconds()` - Server uptime

### Moderation
**[DEVELOPER_GUIDE.md#7-functionsmodemrationpy](DEVELOPER_GUIDE.md#7-functionsmodemrationpy)**

Functions:
- `is_ip_banned()` - Check if banned
- `ban_ip()` - Issue ban
- `create_report()` - File user report

### File Uploads
**[DEVELOPER_GUIDE.md#8-functionsdropzonepy](DEVELOPER_GUIDE.md#8-functionsdropzonepy)**

Functions:
- `dropzone_save()` - Save uploaded file
- `dropzone_search()` - Find uploads
- `dropzone_stats()` - Storage statistics

---

## 🏗️ Architecture & Organization

### Repository Structure
→ **[ORGANIZATION.md](ORGANIZATION.md)**

Complete file layout with:
- Directory descriptions
- File purposes
- Organization by feature
- Development notes

### Architecture Diagrams
→ **[DEVELOPER_GUIDE.md#repository-architecture](DEVELOPER_GUIDE.md#repository-architecture)**

Visual diagrams showing:
- High-level architecture
- Component relationships
- Request/response flow
- Data flow between modules

### Code Organization Phases
→ **[PHASE4_COMPLETION.md#summary-of-all-refactoring-phases](PHASE4_COMPLETION.md#summary-of-all-refactoring-phases)**

Summary of refactoring work:
- **Phase 1**: Blueprint reorganization
- **Phase 2**: Game logic extraction
- **Phase 3**: Functions module split
- **Phase 4**: Documentation (this!)

---

## 🔧 Technical Guides

### Framework & Technologies
→ **[DEVELOPER_GUIDE.md#framework--technologies](DEVELOPER_GUIDE.md#framework--technologies)**

Coverage:
- Flask routing patterns
- Flask-SocketIO socket events
- SQLite3 database usage
- Real-time communication

### WebSocket Events & Real-time
→ **[DEVELOPER_GUIDE.md#socket-events--real-time-communication](DEVELOPER_GUIDE.md#socket-events--real-time-communication)**

Patterns:
- Request-Response
- Broadcast
- Session tracking
- Room/namespace usage

### Configuration Management
→ **[DEVELOPER_GUIDE.md#configuration-management](DEVELOPER_GUIDE.md#configuration-management)**

Topics:
- Adding new settings
- Using configuration values
- Reloading config
- Environment-specific settings

### Logging
→ **[DEVELOPER_GUIDE.md#task-5-log-events](DEVELOPER_GUIDE.md#task-5-log-events)**

Covered:
- Log types (app, error, access)
- Using logger objects
- Log file locations
- Debugging with logs

---

## 📚 Feature Documentation

### Games
Each game in `blueprints/games/` follows the same structure:
- Route file (e.g., `chess.py`)
- Socket events (e.g., `socket_events/chess_events.py`)
- Template (e.g., `templates/chess.html`)
- Game logic (e.g., `game_logic/chess/chess_ai.py`)

**Example structure**: [DEVELOPER_GUIDE.md#step-4-create-rest-endpoints](DEVELOPER_GUIDE.md#step-4-create-rest-endpoints)

### Chat & Messaging
See: **[DEVELOPER_GUIDE.md#2-functionschatpy](DEVELOPER_GUIDE.md#2-functionschatpy)**

- Direct messages
- Channels with passwords
- Rate limiting
- Message editing/deletion

### Admin Panel
Routes in `blueprints/admin/`:
- Admin account management (`admin.py`)
- IP ban management (`bans.py`)
- Database viewer (`db.py`)
- Server control (`power.py`)
- Configuration UI (`server_config.py`)
- Report management (`reports.py`)

### File Upload (Dropzone)
See: **[DEVELOPER_GUIDE.md#8-functionsdropzonepy](DEVELOPER_GUIDE.md#8-functionsdropzonepy)**

Features:
- Upload with validation
- Per-IP rate limiting
- Automatic quota enforcement
- Tag-based search
- File deletion

---

## 🚀 Development Workflow

### Adding a Feature - Step by Step
→ **[DEVELOPER_GUIDE.md#step-1-plan-the-feature](DEVELOPER_GUIDE.md#step-1-plan-the-feature)** (complete 8-step guide)

1. Plan feature
2. Create database table
3. Add business logic
4. Create REST endpoints
5. Add socket handlers
6. Create HTML template
7. Add JavaScript
8. Test

### Common Development Tasks
→ **[DEVELOPER_GUIDE.md#common-development-tasks](DEVELOPER_GUIDE.md#common-development-tasks)**

5 real-world examples:
1. Add new game
2. Add admin feature
3. Query database
4. Add config option
5. Log events

---

## 📋 Checklists & Quick Reference

### Feature Addition Checklist
→ **[DEVELOPER_GUIDE.md#summary-checklist](DEVELOPER_GUIDE.md#summary-checklist)**

Before pushing:
- [ ] Plan feature
- [ ] Add database table
- [ ] Create business logic
- [ ] Create REST endpoints
- [ ] Add Socket events
- [ ] Create/update template
- [ ] Add JavaScript handlers
- [ ] Test in browser
- [ ] Document code
- [ ] Update guides if needed
- [ ] Commit with clear message

### Performance Tips
→ **[DEVELOPER_GUIDE.md#performance-tips](DEVELOPER_GUIDE.md#performance-tips)**

Best practices:
- Use parameterized queries
- Use LIMIT to prevent huge result sets
- Index frequently-queried columns
- Always close database connections

---

## 🐛 Troubleshooting & Debugging

### Common Issues
→ **[DEVELOPER_GUIDE.md#common-issues](DEVELOPER_GUIDE.md#common-issues)**

Solutions for:
- App won't start
- Database locked
- Socket events not firing
- Import errors

### Debug Mode
→ **[DEVELOPER_GUIDE.md#enable-debug-mode](DEVELOPER_GUIDE.md#enable-debug-mode)**

How to:
- Enable debug=True
- Use browser DevTools
- Test socket connection
- Check logs

### Logging
→ **[DEVELOPER_GUIDE.md#check-logs](DEVELOPER_GUIDE.md#check-logs)**

Log files:
- `logs/app.log` - Application events
- `logs/error.log` - Errors only
- `logs/access.log` - HTTP requests
- `logs/github.log` - GitHub sync

---

## 📖 Complete Documentation Files

### For Newcomers
- **[README.md](README.md)** - Project overview (read first!)
- **[ORGANIZATION.md](ORGANIZATION.md)** - Repository structure
- **[DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md)** - Complete developer handbook ⭐

### For Referencing
- **[PHASE4_COMPLETION.md](PHASE4_COMPLETION.md)** - Refactoring summary & status
- **[REFACTORING_PHASE3.md](REFACTORING_PHASE3.md)** - Functions module split details
- **[REFACTORING_NOTES.md](REFACTORING_NOTES.md)** - Phases 1-2 reorganization details

---

## 🎓 Learning Path

### For Python Developers
1. Start with [README.md](README.md)
2. Read [DEVELOPER_GUIDE.md#repository-architecture](DEVELOPER_GUIDE.md#repository-architecture)
3. Explore [blueprints/games/tetris.py](blueprints/games/tetris.py) (simple game)
4. Read [DEVELOPER_GUIDE.md#how-to-add-a-new-feature](DEVELOPER_GUIDE.md#how-to-add-a-new-feature)
5. Create a feature following the guide
6. Ask questions or reference module docs

### For Frontend Developers
1. Start with [README.md](README.md)
2. Check [templates/](templates/) for HTML structure
3. Check [static/js/](static/js/) for JavaScript patterns
4. Read [DEVELOPER_GUIDE.md#socket-events--real-time-communication](DEVELOPER_GUIDE.md#socket-events--real-time-communication)
5. Study existing game templates
6. Create a new feature with updated UI

### For DevOps/Infrastructure
1. Start with [README.md](README.md)
2. Review [ORGANIZATION.md](ORGANIZATION.md)
3. Check [blueprints/admin/](blueprints/admin/) for admin features
4. Read [DEVELOPER_GUIDE.md#configuration-management](DEVELOPER_GUIDE.md#configuration-management)
5. Review logs in [logs/](logs/)
6. Set up monitoring based on server.py functions

---

## 🤝 Contributing

### Before Making Changes
1. Read [DEVELOPER_GUIDE.md](DEVELOPER_GUIDE.md)
2. Check [ORGANIZATION.md](ORGANIZATION.md) for where code goes
3. Follow patterns from existing code
4. Test before committing

### When Adding Features
1. Follow [DEVELOPER_GUIDE.md#step-1-plan-the-feature](DEVELOPER_GUIDE.md#step-1-plan-the-feature) (8 steps)
2. Use checklist at [DEVELOPER_GUIDE.md#summary-checklist](DEVELOPER_GUIDE.md#summary-checklist)
3. Reference core modules in [DEVELOPER_GUIDE.md#core-python-modules](DEVELOPER_GUIDE.md#core-python-modules)
4. Test thoroughly
5. Document in code comments
6. Update this index if you create new documentation

### Questions?
- Check [DEVELOPER_GUIDE.md#getting-help](DEVELOPER_GUIDE.md#getting-help)
- Review module docstrings
- Check function usage examples
- Search existing code for patterns

---

## 📊 Repository Statistics

- **Total Python files**: 50+
- **Lines of code**: ~8000 (organized and maintainable)
- **Documentation pages**: 7 complete guides
- **Modules documented**: 8 core modules with API reference
- **Example features**: 3+ complete examples in guides
- **Games**: 6 fully functional games
- **Database tables**: 20
- **Socket events**: 50+

---

## ✅ Status

- Phase 1: Blueprint Reorganization ✅ Complete
- Phase 2: Game Logic & Utils Extraction ✅ Complete
- Phase 3: Functions Module Decomposition ✅ Complete
- Phase 4: Documentation & Finalization ✅ Complete

**Repository Status**: ✅ Production Ready  
**Developer Ready**: ✅ Fully Documented  
**Contribution Path**: ✅ Clear

---

## 🔗 Quick Links

| Need | Document |
|------|----------|
| Start here | [README.md](README.md) |
| Architecture | [DEVELOPER_GUIDE.md#repository-architecture](DEVELOPER_GUIDE.md#repository-architecture) |
| File structure | [ORGANIZATION.md](ORGANIZATION.md) |
| Add feature | [DEVELOPER_GUIDE.md#how-to-add-a-new-feature](DEVELOPER_GUIDE.md#how-to-add-a-new-feature) |
| Database API | [DEVELOPER_GUIDE.md#1-functionsdbpy](DEVELOPER_GUIDE.md#1-functionsdbpy) |
| Socket events | [DEVELOPER_GUIDE.md#socket-events--real-time-communication](DEVELOPER_GUIDE.md#socket-events--real-time-communication) |
| Debugging | [DEVELOPER_GUIDE.md#debugging--troubleshooting](DEVELOPER_GUIDE.md#debugging--troubleshooting) |
| Refactoring summary | [PHASE4_COMPLETION.md](PHASE4_COMPLETION.md) |

---

**Last Updated**: April 2026  
**Status**: Phase 4 Complete ✅  
**Maintainers**: LANHub Team

Happy coding! 🚀
