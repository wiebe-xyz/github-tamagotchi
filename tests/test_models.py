"""Tests for models and enums."""

from sqlalchemy import String

from github_tamagotchi.models.pet import Pet, PetMood, PetStage


class TestPetStageEnum:
    """Tests for PetStage enum."""

    def test_all_stages_defined(self) -> None:
        """All expected stages should be defined."""
        expected_stages = ["egg", "baby", "child", "teen", "adult", "elder"]
        actual_stages = [stage.value for stage in PetStage]
        assert actual_stages == expected_stages

    def test_stage_count(self) -> None:
        """Should have exactly 6 evolution stages."""
        assert len(PetStage) == 6

    def test_stages_are_strings(self) -> None:
        """Stage values should be lowercase strings."""
        for stage in PetStage:
            assert isinstance(stage.value, str)
            assert stage.value.islower()

    def test_stage_string_representation(self) -> None:
        """PetStage should have proper string representation."""
        assert PetStage.EGG.value == "egg"
        # StrEnum returns the value as the string representation
        assert str(PetStage.EGG) == "egg"


class TestPetMoodEnum:
    """Tests for PetMood enum."""

    def test_all_moods_defined(self) -> None:
        """All expected moods should be defined."""
        expected_moods = ["happy", "content", "hungry", "worried", "lonely", "sick", "dancing"]
        actual_moods = [mood.value for mood in PetMood]
        assert actual_moods == expected_moods

    def test_mood_count(self) -> None:
        """Should have exactly 7 mood types."""
        assert len(PetMood) == 7

    def test_moods_are_strings(self) -> None:
        """Mood values should be lowercase strings."""
        for mood in PetMood:
            assert isinstance(mood.value, str)
            assert mood.value.islower()

    def test_positive_moods(self) -> None:
        """Positive moods should be defined."""
        positive = [PetMood.HAPPY, PetMood.CONTENT, PetMood.DANCING]
        for mood in positive:
            assert mood in PetMood

    def test_negative_moods(self) -> None:
        """Negative moods should be defined."""
        negative = [PetMood.HUNGRY, PetMood.WORRIED, PetMood.LONELY, PetMood.SICK]
        for mood in negative:
            assert mood in PetMood


class TestPetModel:
    """Tests for Pet SQLAlchemy model."""

    def test_tablename(self) -> None:
        """Pet table should be named 'pets'."""
        assert Pet.__tablename__ == "pets"

    def test_default_stage(self) -> None:
        """Default stage should be EGG."""
        # Check the column default
        stage_column = Pet.__table__.columns["stage"]
        assert stage_column.default.arg == PetStage.EGG.value

    def test_default_mood(self) -> None:
        """Default mood should be CONTENT."""
        mood_column = Pet.__table__.columns["mood"]
        assert mood_column.default.arg == PetMood.CONTENT.value

    def test_default_health(self) -> None:
        """Default health should be 100."""
        health_column = Pet.__table__.columns["health"]
        assert health_column.default.arg == 100

    def test_default_experience(self) -> None:
        """Default experience should be 0."""
        exp_column = Pet.__table__.columns["experience"]
        assert exp_column.default.arg == 0

    def test_required_fields(self) -> None:
        """Required fields should not be nullable."""
        required_fields = ["repo_owner", "repo_name", "name"]
        for field_name in required_fields:
            column = Pet.__table__.columns[field_name]
            assert column.nullable is False, f"{field_name} should not be nullable"

    def test_optional_timestamp_fields(self) -> None:
        """Optional timestamp fields should be nullable."""
        optional_fields = ["last_fed_at", "last_checked_at"]
        for field_name in optional_fields:
            column = Pet.__table__.columns[field_name]
            assert column.nullable is True, f"{field_name} should be nullable"

    def test_primary_key(self) -> None:
        """id should be the primary key."""
        id_column = Pet.__table__.columns["id"]
        assert id_column.primary_key is True

    def test_string_field_lengths(self) -> None:
        """String fields should have appropriate max lengths."""
        repo_owner_type = Pet.__table__.columns["repo_owner"].type
        repo_name_type = Pet.__table__.columns["repo_name"].type
        name_type = Pet.__table__.columns["name"].type
        stage_type = Pet.__table__.columns["stage"].type
        mood_type = Pet.__table__.columns["mood"].type

        assert isinstance(repo_owner_type, String) and repo_owner_type.length == 255
        assert isinstance(repo_name_type, String) and repo_name_type.length == 255
        assert isinstance(name_type, String) and name_type.length == 100
        assert isinstance(stage_type, String) and stage_type.length == 20
        assert isinstance(mood_type, String) and mood_type.length == 20
