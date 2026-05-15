"""tests/test_lab.py - Unit tests for HansHub Lab feature."""

import pytest
import time
from functions import lab
from dependencies import DI


@pytest.mark.unit
class TestLabUserManagement:
    """Tests for Lab user creation and authentication."""
    
    def test_create_lab_user(self, mock_db):
        """Test creating a new Lab user."""
        user = lab.lab_user_create("testuser", "password123")
        
        assert user is not None
        assert user["username"] == "testuser"
        assert user["quota_mb"] == 500  # default
    
    def test_create_duplicate_user(self, mock_db):
        """Test that duplicate usernames are rejected."""
        lab.lab_user_create("testuser", "password123")
        duplicate = lab.lab_user_create("testuser", "different_password")
        
        assert duplicate is None
    
    def test_authenticate_user(self, mock_db):
        """Test user authentication."""
        lab.lab_user_create("testuser", "password123")
        user = lab.lab_user_authenticate("testuser", "password123")
        
        assert user is not None
        assert user["username"] == "testuser"
        assert user["session_token"] is not None
    
    def test_authenticate_wrong_password(self, mock_db):
        """Test authentication with wrong password."""
        lab.lab_user_create("testuser", "password123")
        user = lab.lab_user_authenticate("testuser", "wrongpassword")
        
        assert user is None
    
    def test_verify_session(self, mock_db):
        """Test session verification."""
        lab.lab_user_create("testuser", "password123")
        user = lab.lab_user_authenticate("testuser", "password123")
        session_token = user["session_token"]
        
        verified = lab.lab_user_verify_session("testuser", session_token)
        assert verified is not None
        assert verified["username"] == "testuser"


@pytest.mark.unit
class TestProjectManagement:
    """Tests for project CRUD operations."""
    
    def test_create_project(self, mock_db):
        """Test creating a new project."""
        user = lab.lab_user_create("testuser", "password123")
        
        project = lab.project_create(
            owner_id=user["id"],
            title="My Test Project",
            description="A test project"
        )
        
        assert project is not None
        assert project["title"] == "My Test Project"
        assert project["owner_id"] == user["id"]
    
    def test_project_slug_generation(self, mock_db):
        """Test that project slugs are generated correctly."""
        user = lab.lab_user_create("testuser", "password123")
        
        project = lab.project_create(
            owner_id=user["id"],
            title="My Awesome Project!"
        )
        
        assert project["slug"] is not None
        assert " " not in project["slug"]
        assert "!" not in project["slug"]
    
    def test_get_project_by_slug(self, mock_db):
        """Test retrieving projects by slug."""
        user = lab.lab_user_create("testuser", "password123")
        
        created = lab.project_create(
            owner_id=user["id"],
            title="My Project"
        )
        
        retrieved = lab.project_get_by_slug(created["slug"])
        assert retrieved is not None
        assert retrieved["id"] == created["id"]
    
    def test_list_projects_by_owner(self, mock_db):
        """Test listing projects by owner."""
        user = lab.lab_user_create("testuser", "password123")
        
        project1 = lab.project_create(user["id"], "Project 1", "flask")
        project2 = lab.project_create(user["id"], "Project 2", "fastapi")
        
        projects = lab.project_list_by_owner(user["id"])
        
        assert len(projects) == 2
        assert any(p["id"] == project1["id"] for p in projects)
        assert any(p["id"] == project2["id"] for p in projects)
    
    def test_update_project(self, mock_db):
        """Test updating project fields."""
        user = lab.lab_user_create("testuser", "password123")
        project = lab.project_create(user["id"], "Project", "flask")
        
        success = lab.project_update(project["id"], {
            "title": "Updated Title",
            "description": "New description"
        })
        
        assert success
        updated = lab.project_get_by_id(project["id"])
        assert updated["title"] == "Updated Title"
        assert updated["description"] == "New description"
    
    def test_delete_project(self, mock_db):
        """Test deleting a project."""
        user = lab.lab_user_create("testuser", "password123")
        project = lab.project_create(user["id"], "Project", "flask")
        
        success = lab.project_delete(project["id"])
        assert success
        
        deleted = lab.project_get_by_id(project["id"])
        assert deleted is None


@pytest.mark.unit
class TestProjectMembers:
    """Tests for project collaboration and membership."""
    
    def test_add_project_member(self, mock_db):
        """Test adding a member to a project."""
        owner = lab.lab_user_create("owner", "password")
        contributor = lab.lab_user_create("contributor", "password")
        
        project = lab.project_create(owner["id"], "Project", "flask")
        success = lab.project_member_add(project["id"], contributor["id"], "contributor")
        
        assert success
    
    def test_get_project_role(self, mock_db):
        """Test getting a user's role in a project."""
        owner = lab.lab_user_create("owner", "password")
        contributor = lab.lab_user_create("contributor", "password")
        
        project = lab.project_create(owner["id"], "Project", "flask")
        role = lab.project_member_get_role(project["id"], owner["id"])
        
        assert role == "owner"
        
        lab.project_member_add(project["id"], contributor["id"], "contributor")
        role = lab.project_member_get_role(project["id"], contributor["id"])
        
        assert role == "contributor"
    
    def test_cannot_add_duplicate_member(self, mock_db):
        """Test that adding the same member twice fails."""
        owner = lab.lab_user_create("owner", "password")
        user = lab.lab_user_create("user", "password")
        
        project = lab.project_create(owner["id"], "Project", "flask")
        success1 = lab.project_member_add(project["id"], user["id"], "contributor")
        success2 = lab.project_member_add(project["id"], user["id"], "viewer")
        
        assert success1
        assert not success2
    
    def test_can_edit_project(self, mock_db):
        """Test permissions for editing projects."""
        owner = lab.lab_user_create("owner", "password")
        viewer = lab.lab_user_create("viewer", "password")
        
        project = lab.project_create(owner["id"], "Project", "flask")
        lab.project_member_add(project["id"], viewer["id"], "viewer")
        
        assert lab.project_can_edit(project["id"], owner["id"])
        assert not lab.project_can_edit(project["id"], viewer["id"])


@pytest.mark.unit
class TestProjectComments:
    """Tests for project commenting system."""
    
    def test_create_comment(self, mock_db):
        """Test creating a comment on a project."""
        user = lab.lab_user_create("user", "password")
        project = lab.project_create(user["id"], "Project", "flask")
        
        comment = lab.lab_comment_create(
            project["id"],
            user["id"],
            "Great project!"
        )
        
        assert comment is not None
        assert comment["content"] == "Great project!"
    
    def test_list_comments(self, mock_db):
        """Test listing comments on a project."""
        user = lab.lab_user_create("user", "password")
        project = lab.project_create(user["id"], "Project", "flask")
        
        comment1 = lab.lab_comment_create(project["id"], user["id"], "Comment 1")
        comment2 = lab.lab_comment_create(project["id"], user["id"], "Comment 2")
        
        comments = lab.lab_comment_list(project["id"])
        
        assert len(comments) == 2
    
    def test_update_comment(self, mock_db):
        """Test updating a comment."""
        user = lab.lab_user_create("user", "password")
        project = lab.project_create(user["id"], "Project", "flask")
        
        comment = lab.lab_comment_create(project["id"], user["id"], "Original")
        success = lab.lab_comment_update(comment["id"], "Updated")
        
        assert success
        updated = lab.lab_comment_get_by_id(comment["id"])
        assert updated["content"] == "Updated"
    
    def test_delete_comment(self, mock_db):
        """Test deleting a comment."""
        user = lab.lab_user_create("user", "password")
        project = lab.project_create(user["id"], "Project", "flask")
        
        comment = lab.lab_comment_create(project["id"], user["id"], "Comment")
        success = lab.lab_comment_delete(comment["id"])
        
        assert success
        deleted = lab.lab_comment_get_by_id(comment["id"])
        assert deleted is None


@pytest.mark.unit
class TestProjectScaffolding:
    """Tests for project template scaffolding."""
    
    def test_scaffold_flask_project(self, mock_db):
        """Test Flask project scaffolding."""
        user = lab.lab_user_create("user", "password")
        project = lab.project_create(user["id"], "Flask App", "flask")
        
        # This would require filesystem access, so we just test it doesn't crash
        success = lab.project_scaffold(project)
        # Note: actual filesystem operations are mocked in test environment
