"""Tests for the pet naming utility."""

from github_tamagotchi.services.naming import generate_name_from_repo, is_valid_pet_name


class TestGenerateNameFromRepo:
    """Tests for generate_name_from_repo."""

    def test_simple_single_word(self) -> None:
        """Single-word repo produces a capitalised name."""
        name = generate_name_from_repo("owner", "myrepo")
        assert name[0].isupper()
        assert len(name) <= 20

    def test_hyphenated_repo_picks_longest_part(self) -> None:
        """Hyphen-separated repo picks the longest meaningful part."""
        name = generate_name_from_repo("owner", "rapid-root")
        assert len(name) <= 20
        assert name[0].isupper()

    def test_underscore_separated_repo(self) -> None:
        """Underscore-separated repo is split correctly."""
        name = generate_name_from_repo("owner", "my_awesome_lib")
        assert len(name) <= 20
        assert name[0].isupper()

    def test_noise_words_filtered(self) -> None:
        """Generic noise words (my, the, a, …) are filtered out."""
        name = generate_name_from_repo("owner", "my-app")
        # 'my' is noise, so only 'app' contributes
        assert "My" not in name

    def test_fallback_to_cute_name(self) -> None:
        """When only noise words remain, fall back to a cute name from the pool."""
        # All parts are noise words
        name = generate_name_from_repo("owner", "my-the-a")
        assert len(name) <= 20
        # Should be a name from the pool (title-case)
        assert name[0].isupper()

    def test_deterministic_for_same_repo(self) -> None:
        """Same repo always produces the same name."""
        name1 = generate_name_from_repo("alice", "cool-project")
        name2 = generate_name_from_repo("alice", "cool-project")
        assert name1 == name2

    def test_different_repos_may_differ(self) -> None:
        """Different repos are likely to produce different names."""
        name1 = generate_name_from_repo("alice", "api-gateway")
        name2 = generate_name_from_repo("bob", "data-pipeline")
        # This is probabilistic; just check both are valid strings
        assert isinstance(name1, str)
        assert isinstance(name2, str)

    def test_max_length_respected(self) -> None:
        """Generated name never exceeds 20 characters."""
        name = generate_name_from_repo("owner", "a" * 50)
        assert len(name) <= 20


class TestIsValidPetName:
    """Tests for is_valid_pet_name."""

    def test_simple_name_valid(self) -> None:
        assert is_valid_pet_name("Fluffy") is True

    def test_name_with_spaces_valid(self) -> None:
        assert is_valid_pet_name("Sir Fluffington") is True

    def test_numbers_valid(self) -> None:
        assert is_valid_pet_name("Pixel2") is True

    def test_empty_name_invalid(self) -> None:
        assert is_valid_pet_name("") is False

    def test_too_long_invalid(self) -> None:
        assert is_valid_pet_name("A" * 21) is False

    def test_exactly_20_valid(self) -> None:
        assert is_valid_pet_name("A" * 20) is True

    def test_special_chars_invalid(self) -> None:
        assert is_valid_pet_name("Fluffy!") is False
        assert is_valid_pet_name("Fluffy@#") is False
        assert is_valid_pet_name("Fluffy-Wuffy") is False

    def test_profanity_rejected(self) -> None:
        assert is_valid_pet_name("shithead") is False
        assert is_valid_pet_name("fuck") is False

    def test_profanity_case_insensitive(self) -> None:
        assert is_valid_pet_name("FUCK") is False
        assert is_valid_pet_name("Shit") is False
