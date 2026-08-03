import pytest

from app import app


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


def test_developer_playground_listing_page(client):
    response = client.get("/developer_playground")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Developer's Playground" in html
    assert "Sound Visualizer" in html
    assert "/developer_playground/sound-visualizer" in html


def test_developer_playground_sound_visualizer_route(client):
    response = client.get("/developer_playground/sound-visualizer")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Audio Visualizer Baseline" in html
