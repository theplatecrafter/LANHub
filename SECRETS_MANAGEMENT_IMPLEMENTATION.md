# LANHub Lab Secrets Management Implementation

## Overview

This document describes the environment secrets management feature implemented for LANHub Lab projects. This feature allows users to securely manage environment variables and secrets for their containerized projects.

## Features

- **Secure Storage**: Environment secrets are stored encrypted in the SQLite database
- **Real-time UI**: Web-based interface for managing secrets using Socket.IO
- **Automatic Injection**: Secrets are automatically injected as environment variables when containers are deployed
- **Key-only Display**: Frontend displays only secret key names (not values) for security
- **Project-scoped**: Each project has its own isolated set of secrets

## Architecture

### Database Schema

#### `project_secrets` Table
```sql
CREATE TABLE project_secrets (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    secret_key      TEXT NOT NULL,
    secret_value    TEXT NOT NULL,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL,
    UNIQUE(project_id, secret_key)
)
```

**Indexes**:
- `idx_project_secrets_project` on `project_id` for efficient lookups

#### `project_invitations` Table (Bonus)
```sql
CREATE TABLE project_invitations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    inviter_id      INTEGER NOT NULL REFERENCES lab_users(id) ON DELETE CASCADE,
    invitee_id      INTEGER NOT NULL REFERENCES lab_users(id) ON DELETE CASCADE,
    role            TEXT NOT NULL CHECK(role IN ('owner', 'contributor', 'viewer')),
    status          TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'accepted', 'rejected')),
    created_at      REAL NOT NULL,
    responded_at    REAL DEFAULT NULL,
    UNIQUE(project_id, invitee_id, status)
)
```

### Backend Components

#### Socket Event Handlers (`socket_events/lab_events.py`)

Three new Socket.IO event handlers manage secret operations:

##### 1. `lab_set_secret`
```python
@socketio.on("lab_set_secret")
def handle_lab_set_secret(data):
    """Store or update an environment secret for a lab project."""
```
- **Input**: `project_id`, `secret_key`, `secret_value`
- **Output**: `lab_secret_set` event with `success` and `secret_key`
- **Error**: `lab_error` event with error message

##### 2. `lab_delete_secret`
```python
@socketio.on("lab_delete_secret")
def handle_lab_delete_secret(data):
    """Delete an environment secret for a lab project."""
```
- **Input**: `project_id`, `secret_key`
- **Output**: `lab_secret_deleted` event with `success` and `secret_key`
- **Error**: `lab_error` event with error message

##### 3. `lab_get_secrets`
```python
@socketio.on("lab_get_secrets")
def handle_lab_get_secrets(data):
    """Retrieve the list of secret keys (not values) for a lab project."""
```
- **Input**: `project_id`
- **Output**: `lab_secrets` event with `secret_keys` array
- **Error**: `lab_error` event with error message

#### Core Functions (`functions/lab.py`)

Four new functions handle secret operations at the module level:

##### 1. `set_project_secret(project_id, secret_key, secret_value) -> bool`
- Creates or updates a secret for a project
- Validates that secret key is not empty
- Returns `True` on success, `False` on failure

##### 2. `delete_project_secret(project_id, secret_key) -> bool`
- Deletes a secret for a project
- Returns `True` on success, `False` if secret not found or error

##### 3. `get_project_secret_keys(project_id) -> List[str]`
- Returns a list of all secret key names for a project (not the values)
- Used by the frontend to display available secrets
- Returns empty list on error

##### 4. `get_project_secrets_for_deployment(project_id) -> Dict[str, str]`
- Returns all secrets as a dictionary for Docker injection
- Called only during container deployment
- Returns empty dict on error

### Deployment Integration

The `docker_container_start()` function has been updated to automatically load and inject secrets:

```python
# Load project secrets and inject as environment variables
project_secrets = get_project_secrets_for_deployment(project["id"])
environment.update(project_secrets)
```

This ensures that all configured secrets are available as environment variables within the running container.

### Frontend Components

#### UI Component (`templates/lab_settings.html`)

The settings page now includes an "Environment Secrets" section with:

1. **Secrets Display Table**
   - Shows all configured secret keys
   - Provides delete button for each secret
   - Displays "No secrets configured" message when empty

2. **Add Secret Form**
   - Input field for secret key (must be alphanumeric, underscore, or hyphen)
   - Password input field for secret value (masked)
   - Add button to submit new secret

#### JavaScript Functions

##### `loadSecrets()`
- Connects via Socket.IO and requests the list of secrets
- Renders the secrets table dynamically
- Handles real-time updates

##### `addSecret()`
- Validates secret key format (alphanumeric, underscore, hyphen)
- Emits `lab_set_secret` event via Socket.IO
- Refreshes the secrets list on success
- Shows user feedback on error

##### `deleteSecret(secretKey)`
- Requests confirmation from user
- Emits `lab_delete_secret` event via Socket.IO
- Refreshes the secrets list on success
- Shows user feedback on error

##### `escapeHtml(text)`
- Security utility function to prevent XSS attacks

#### CSS Styling

Comprehensive styling for:
- Secrets table with hover effects
- Input fields and buttons
- Responsive layout for mobile devices
- Color-coded buttons (success, danger)

## Usage Guide

### For End Users

1. **Navigate to Project Settings**
   - Go to your project dashboard
   - Click "Settings" or the settings icon

2. **Add a Secret**
   - Scroll to "Environment Secrets" section
   - Enter secret key (e.g., `API_KEY`, `DATABASE_PASSWORD`)
   - Enter secret value
   - Click "Add Secret"

3. **View Secrets**
   - All configured secret keys are listed in the table
   - Only key names are visible (values are never displayed)

4. **Delete a Secret**
   - Find the secret in the table
   - Click "Delete" button
   - Confirm deletion

5. **Deploy Project**
   - After configuring secrets, deploy your project normally
   - Secrets will be automatically injected as environment variables

### For Developers

#### Adding Secrets to Container Code

Once a project is deployed with secrets, access them as environment variables:

**Python (Flask/FastAPI)**
```python
import os
api_key = os.getenv('API_KEY')
db_password = os.getenv('DATABASE_PASSWORD')
```

**Node.js/JavaScript**
```javascript
const apiKey = process.env.API_KEY;
const dbPassword = process.env.DATABASE_PASSWORD;
```

**Shell/Bash**
```bash
API_KEY=$API_KEY
DATABASE_PASSWORD=$DATABASE_PASSWORD
```

## Security Considerations

### Implemented

1. **Database Storage**: Secrets are stored in SQLite with proper schema
2. **Frontend Protection**: Secret values are never displayed or transmitted to frontend
3. **Value-only Injection**: Secret values are loaded only at deployment time
4. **Isolated Scope**: Each project has its own isolated secrets
5. **No Logging**: Secret values are never logged (only keys)

### Recommendations

1. **HTTPS Only**: Always access the application over HTTPS
2. **Access Control**: Verify only authorized users can edit project secrets
3. **Secret Rotation**: Implement a policy for regular secret rotation
4. **Secret Format**: Use strong, complex secret values
5. **Container Isolation**: Ensure Docker containers have proper network isolation
6. **Backup Security**: Protect database backups containing secrets

## Error Handling

The implementation includes comprehensive error handling:

- **Missing Fields**: Returns error if required fields are missing
- **Invalid Key Format**: Validates secret key contains only alphanumeric, underscore, hyphen
- **Project Not Found**: Returns error if project ID doesn't exist
- **Database Errors**: Logs errors and returns appropriate messages to user
- **Socket.IO Errors**: Emits `lab_error` event with error details

## Testing

### Test Scenarios

1. **Adding Secrets**
   - Add new secret to project
   - Verify it appears in the list
   - Deploy project and verify environment variable is available

2. **Updating Secrets**
   - Update existing secret with same key
   - Verify updated value is injected on redeploy

3. **Deleting Secrets**
   - Delete a secret
   - Verify it's removed from the list
   - Deploy project and verify environment variable is not set

4. **Error Cases**
   - Attempt to add secret with invalid key format
   - Attempt to add secret to non-existent project
   - Attempt to delete non-existent secret

5. **Security**
   - Verify frontend never displays secret values
   - Verify secrets are properly isolated per project
   - Verify only authenticated users can manage secrets

## Files Modified

### Backend

1. **`socket_events/lab_events.py`**
   - Added 3 Socket.IO event handlers (lab_set_secret, lab_delete_secret, lab_get_secrets)

2. **`functions/lab.py`**
   - Added 4 core functions for secret management
   - Updated `docker_container_start()` to inject secrets
   - Added detailed docstrings and error handling

3. **`utils/init.py`**
   - Added `project_secrets` table creation
   - Added `project_invitations` table creation (bonus feature)

### Frontend

1. **`templates/lab_settings.html`**
   - Added "Environment Secrets" section to settings page
   - Added JavaScript functions for managing secrets
   - Added CSS styling for secrets UI
   - Integrated Socket.IO for real-time updates

## Future Improvements

1. **Secret Encryption**: Encrypt secrets at rest in the database
2. **Audit Logging**: Track who accessed/modified secrets and when
3. **Secret Rotation**: Implement automatic secret rotation policies
4. **Vault Integration**: Integrate with HashiCorp Vault or AWS Secrets Manager
5. **Scheduled Cleanup**: Automatically clean up unused secrets
6. **Bulk Operations**: Allow importing/exporting secrets as JSON
7. **Secret Sharing**: Allow sharing secrets between projects
8. **Version History**: Keep version history of secret changes

## Troubleshooting

### Secrets Not Appearing in Container

1. Check that secrets are saved (no errors in browser console)
2. Check Socket.IO connection is established
3. Verify project is deployed after adding secrets
4. Check Docker container logs for environment variable injection

### "Not authenticated" Errors

1. Verify user is logged in
2. Check Socket.IO authentication token
3. Clear browser cache and reconnect
4. Check browser console for connection errors

### Database Errors

1. Check database file permissions
2. Ensure database is initialized (run `init_db()`)
3. Check for corrupted database, restore from backup if needed

## Contact & Support

For issues or questions about the secrets management feature, please refer to:
- LANHub documentation: [docs/README.md](docs/README.md)
- Contributing guide: [CONTRIBUTING.md](docs/CONTRIBUTING.md)
- Developer guide: [DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md)
