from __future__ import annotations

from wsc_pipeline.config import LEAGUES, LEAGUES_EXAMINED_NOT_INCLUDED, league_by_slug


def test_ausl_is_tracked_with_six_permanent_franchises():
    """AUSL (Athletes Unlimited's softball league) was added 2026-09-14,
    docs/DECISIONS.md 0008 -- six city-based franchises, same shape as
    WNBA/NWSL/PWHL, sourced from the 2026 AUSL season (Wikipedia/ESPN)."""
    ausl = league_by_slug("ausl")
    assert ausl.name == "AUSL"
    assert ausl.country_codes == ("US",)
    team_names = {team.name for team in ausl.teams}
    assert team_names == {
        "Chicago Bandits",
        "Carolina Blaze",
        "Portland Cascade",
        "Oklahoma City Spark",
        "Utah Talons",
        "Texas Volts",
    }
    assert len(ausl.teams) == 6


def test_ausl_schedule_source_not_used_but_still_a_tracked_league():
    """Same shape as WNBA/NWSL/PWHL: the league's own schedule is never
    read (docs/DECISIONS.md 0006), but the league is still tracked via
    Ticketmaster team-keyword search -- schedule_source_used=False must not
    be confused with "not tracked"."""
    ausl = league_by_slug("ausl")
    assert ausl.schedule_source_used is False
    assert "not used" in ausl.schedule_source_note.lower()
    assert "ticketmaster" in ausl.schedule_source_note.lower()


def test_every_tracked_league_has_a_nonempty_schedule_source_note():
    for league in LEAGUES:
        assert league.schedule_source_note.strip(), f"{league.slug} has no schedule_source_note"
        assert league.teams, f"{league.slug} has no teams configured"


def test_team_slugs_are_unique_within_ausl():
    slugs = [team.slug for team in league_by_slug("ausl").teams]
    assert len(slugs) == len(set(slugs))


def test_team_slugs_are_unique_across_the_whole_registry():
    """A slug collision across leagues would silently overwrite one
    league's per-team .ics/site output with another's during build."""
    all_slugs = [(lg.slug, team.slug) for lg in LEAGUES for team in lg.teams]
    assert len(all_slugs) == len(set(all_slugs))


def test_leagues_examined_not_included_still_has_five_entries():
    """NCAA, Unrivaled, LOVB, the three non-softball Athletes Unlimited
    disciplines, and USL W League (added 2026-09-16, docs/DECISIONS.md
    0009 -- examined and rejected on Ticketmaster coverage, not licensing).
    Mirrors tests/test_build.py's site.json assertion on this same list."""
    assert len(LEAGUES_EXAMINED_NOT_INCLUDED) == 5


def test_usl_w_league_examined_and_excluded_for_coverage_not_licensing():
    """USL W League (docs/DECISIONS.md 0009): licensing was moot, same as
    every tracked league, but a 16-club Ticketmaster spot-check across the
    96-club 2026 roster found zero clubs with confirmed current coverage,
    so it stays untracked -- this must not be confused with an
    unscoped/unchecked exclusion like Unrivaled or LOVB."""
    names = [item["name"] for item in LEAGUES_EXAMINED_NOT_INCLUDED]
    assert "USL W League" in names
    entry = next(item for item in LEAGUES_EXAMINED_NOT_INCLUDED if item["name"] == "USL W League")
    assert "96 clubs" in entry["reason"]
    assert "ticketmaster" in entry["reason"].lower()
    assert "coverage, not licensing" in entry["reason"]
    assert "0009" in entry["reason"]


def test_usl_w_league_is_not_a_tracked_league():
    """The exclusion in LEAGUES_EXAMINED_NOT_INCLUDED must correspond to an
    actual absence from LEAGUES -- otherwise the two lists would
    contradict each other on the site's own "leagues examined" page."""
    try:
        league_by_slug("usl-w-league")
    except KeyError:
        pass
    else:
        raise AssertionError("USL W League must not be a tracked league (docs/DECISIONS.md 0009)")


def test_athletes_unlimited_exclusion_is_scoped_to_non_softball_disciplines():
    """The bare "Athletes Unlimited" entry must not still exist once AUSL
    is tracked -- that would contradict config.py's own LEAGUES tuple on
    the site's own "leagues examined and not included" page."""
    names = [item["name"] for item in LEAGUES_EXAMINED_NOT_INCLUDED]
    assert "Athletes Unlimited" not in names
    matches = [item for item in LEAGUES_EXAMINED_NOT_INCLUDED if "Athletes Unlimited" in item["name"]]
    assert len(matches) == 1
    entry = matches[0]
    assert "basketball" in entry["name"].lower()
    assert "lacrosse" in entry["name"].lower()
    assert "volleyball" in entry["name"].lower()
    assert "ausl" in entry["reason"].lower()
    assert "not a licensing gap" in entry["reason"].lower()


def test_leagues_examined_not_included_reasons_still_present():
    for expected in ("NCAA", "Unrivaled", "LOVB"):
        assert any(expected in item["name"] for item in LEAGUES_EXAMINED_NOT_INCLUDED)
