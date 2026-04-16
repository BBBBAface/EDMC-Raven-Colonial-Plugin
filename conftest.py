import pytest

@pytest.fixture
def mock_journal_jump():
    """Simulates a standard, well-formed FSD jump event."""
    return {
        "timestamp": "2026-03-27T20:00:00Z",
        "event": "FSDJump",
        "StarSystem": "Colonia",
        "StarPos": [-9530.5, -910.28125, 19808.125]
    }

@pytest.fixture
def mock_malformed_jump():
    """Simulates a corrupted journal entry."""
    return {
        "timestamp": "2026-03-27T20:01:00Z",
        "event": "FSDJump"
        # Missing StarSystem and StarPos
    }

def test_hud_data_extraction(mock_journal_jump):
    system = mock_journal_jump.get("StarSystem", "Unknown System")
    assert system == "Colonia"

def test_malformed_data_handling(mock_malformed_jump):
    system = mock_malformed_jump.get("StarSystem", "Unknown System")
    pos = mock_malformed_jump.get("StarPos", [0, 0, 0])
    assert system == "Unknown System"
    assert pos == [0, 0, 0]