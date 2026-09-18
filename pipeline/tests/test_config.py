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


def test_leagues_examined_not_included_now_has_six_entries():
    """NCAA, Unrivaled, LOVB, the three non-softball Athletes Unlimited
    disciplines, WPBL (docs/DECISIONS.md 0011, added 2026-09-16 -- zero
    Ticketmaster coverage, not a licensing block), and USL W League
    (docs/DECISIONS.md 0014, added 2026-09-16 -- examined and rejected on
    Ticketmaster coverage, not licensing). Mirrors tests/test_build.py's
    site.json assertion on this same list."""
    assert len(LEAGUES_EXAMINED_NOT_INCLUDED) == 6


def test_wpbl_is_examined_and_excluded_for_zero_ticketmaster_coverage():
    """WPBL is a real, currently operating league with fixed team
    franchises (same shape as WNBA/NWSL/PWHL/AUSL), so this must not read
    like a licensing or team-identity exclusion -- the reason must name
    the actual, empirical blocker: zero Ticketmaster coverage."""
    matches = [item for item in LEAGUES_EXAMINED_NOT_INCLUDED if "WPBL" in item["name"]]
    assert len(matches) == 1
    entry = matches[0]
    reason = entry["reason"].lower()
    assert "ticketmaster" in reason
    assert "zero" in reason
    assert "not a licensing gap" in reason
    assert "wnba" in reason or "ausl" in reason  # team-identity shape acknowledged, not the blocker


def test_wpbl_is_not_a_tracked_league():
    """The dispositive finding (zero Ticketmaster coverage across all four
    2026 teams) means WPBL must not appear in the tracked LEAGUES tuple."""
    slugs = [league.slug for league in LEAGUES]
    assert "wpbl" not in slugs
    names = [league.name for league in LEAGUES]
    assert not any("WPBL" in name or "Women's Pro Baseball" in name for name in names)


def test_usl_w_league_examined_and_excluded_for_coverage_not_licensing():
    """USL W League (docs/DECISIONS.md 0014): licensing was moot, same as
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


def test_usl_w_league_is_not_a_tracked_league():
    """The exclusion in LEAGUES_EXAMINED_NOT_INCLUDED must correspond to an
    actual absence from LEAGUES -- otherwise the two lists would
    contradict each other on the site's own "leagues examined" page."""
    try:
        league_by_slug("usl-w-league")
    except KeyError:
        pass
    else:
        raise AssertionError("USL W League must not be a tracked league (docs/DECISIONS.md 0014)")


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
    for expected in ("NCAA", "Unrivaled", "LOVB", "WPBL", "USL W League"):
        assert any(expected in item["name"] for item in LEAGUES_EXAMINED_NOT_INCLUDED)


def test_ncaaw_big_ten_is_tracked_with_eighteen_teams():
    """NCAA women's basketball (Big Ten only) was added 2026-09-16,
    docs/DECISIONS.md 0010 -- the conference's 18 members for the 2026-27
    season, after confirming real Ticketmaster inventory per team (unlike
    the other tracked leagues, a bare school nickname is shared across
    every sport, so team names carry a 'Womens Basketball' suffix)."""
    ncaaw = league_by_slug("ncaaw-big-ten")
    assert ncaaw.name == "NCAA Women's Basketball (Big Ten)"
    assert ncaaw.country_codes == ("US",)
    assert len(ncaaw.teams) == 18
    for team in ncaaw.teams:
        assert team.name.endswith("Womens Basketball")


def test_ncaaw_big_ten_schedule_source_not_used_but_still_a_tracked_league():
    """Same shape as WNBA/NWSL/PWHL/AUSL: no NCAA or school site is read
    (docs/DECISIONS.md 0006), but the league is still tracked via
    Ticketmaster team-keyword search."""
    ncaaw = league_by_slug("ncaaw-big-ten")
    assert ncaaw.schedule_source_used is False
    assert "not" in ncaaw.schedule_source_note.lower()
    assert "ticketmaster" in ncaaw.schedule_source_note.lower()


def test_team_slugs_are_unique_within_ncaaw_big_ten():
    slugs = [team.slug for team in league_by_slug("ncaaw-big-ten").teams]
    assert len(slugs) == len(set(slugs))


def test_ncaa_exclusion_is_scoped_to_outside_the_big_ten():
    """The bare "NCAA women's sports" entry must not still exist once
    Big Ten women's basketball is tracked -- that would contradict
    config.py's own LEAGUES tuple on the site's "leagues examined and not
    included" page, same reasoning as the Athletes Unlimited rescoping."""
    names = [item["name"] for item in LEAGUES_EXAMINED_NOT_INCLUDED]
    assert "NCAA women's sports" not in names
    matches = [item for item in LEAGUES_EXAMINED_NOT_INCLUDED if "NCAA" in item["name"]]
    assert len(matches) == 1
    entry = matches[0]
    assert "big ten" in entry["name"].lower()
    assert "not a licensing gap" in entry["reason"].lower()
    assert "not yet scoped" in entry["reason"].lower()
