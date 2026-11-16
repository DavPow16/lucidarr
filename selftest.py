"""Offline self-test of the pure logic (no browser, no network)."""

import asyncio as _aio

from lucidadl import utils, matching
from lucidadl.api import (
    LucidaClient, normalize_service, default_country, _long, _apple_tracks_from_obj,
    _apple_playlist_from_scripts, is_apple_playlist_url, playlist_source,
    _spotify_playlist_from_html, _spotify_total_from_html,
    _deezer_playlist_from_obj, _tidal_playlist_from_html, _tidal_items_from_obj,
    _amazon_playlist_from_html, _qobuz_playlist_from_obj, DOWNSCALE_CHOICES,
)
from lucidadl.models import FailedItem

fails = []


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    if not cond:
        fails.append(name)


# naming
check("sanitize strips bad chars", utils.sanitize('AC/DC: Back?*') == "AC_DC_ Back__")
check("sanitize reserved", utils.sanitize("CON").startswith("_"))
check("artists_str", utils.artists_str([{"name": "A"}, {"name": "B"}]) == "A, B")
check("artists_str empty", utils.artists_str([]) == "Unknown Artist")
check("year_of", utils.year_of("1999-06-08T00:00:00Z") == "1999")

# sanitize_filename preserves the extension even when truncating a long name
_long_name = ("Red Hot Chili Peppers - " + "x" * 300 + ".flac")
_sf = utils.sanitize_filename(_long_name)
check("sanitize_filename keeps .flac", _sf.endswith(".flac"))
check("sanitize_filename capped", len(_sf) <= 192)
check("sanitize_filename strips bad chars", "/" not in utils.sanitize_filename("a/b:c.zip"))
# A name that merely CONTAINS a dot ("Song. Extended Version Here") has no file
# extension: the text after the last dot is part of the title and must survive
# intact, and the name must not be truncated to a made-up extension.
check("sanitize_filename keeps a dotted title intact",
      utils.sanitize_filename("Song. Extended Version Here")
      == "Song. Extended Version Here")
check("sanitize_filename keeps a dotted title with a short tail",
      utils.sanitize_filename("Mr. Blue Sky") == "Mr. Blue Sky")

# services / country
check("normalize amazon_music", normalize_service("amazon_music") == "amazon")
check("default_country qobuz=NL", default_country("qobuz") == "NL")
check("default_country amazon=''", default_country("amazon") == "")
check("download country for grilledcheese is auto",
      default_country("grilledcheese") == "")
check("default_country other=US", default_country("tidal") == "US")
check("formats", DOWNSCALE_CHOICES[0] == "original" and "flac" in DOWNSCALE_CHOICES)
check("Apple URL validation accepts playlists only",
      is_apple_playlist_url("https://music.apple.com/fr/playlist/mix/pl.123")
      and not is_apple_playlist_url("https://music.apple.com/fr/album/record/123")
      and not is_apple_playlist_url("https://example.com/playlist/mix/pl.123"))
check("public playlist source detection",
      playlist_source("https://music.apple.com/fr/playlist/mix/pl.123") == "apple"
      and playlist_source("https://open.spotify.com/playlist/abc?si=share") == "spotify"
      and playlist_source("https://www.deezer.com/fr/playlist/123") == "deezer"
      and playlist_source("https://music.youtube.com/playlist?list=PL123") == "youtube"
      and playlist_source("https://tidal.com/playlist/123") == "tidal"
      and playlist_source("https://soundcloud.com/artist/sets/mix") == "soundcloud"
      and playlist_source("https://open.qobuz.com/playlist/123") == "qobuz"
      and playlist_source("https://music.amazon.com/user-playlists/123") == "amazon"
      and playlist_source("https://open.spotify.com/album/abc") == "")

# long path (Windows)
import os as _os
if _os.name == "nt":
    check("long path prefix on Windows", _long("C:\\a\\b").startswith("\\\\?\\"))
else:
    check("long path passthrough off Windows", _long("/a/b") == "/a/b")

# Apple Music JSON extractor (still used as a helper / future fallback)
sample = {"data": [{"type": "playlists", "attributes": {"name": "My PL"},
          "relationships": {"tracks": {"data": [
              {"type": "songs", "attributes": {"name": "Otherside", "artistName": "RHCP"}},
              {"type": "songs", "attributes": {"name": "Scar Tissue", "artistName": "RHCP"}},
          ]}}}]}
out = []
_apple_tracks_from_obj(sample, out)
check("apple extractor: 2 songs, playlist node skipped",
      len(out) == 2 and out[0] == {"title": "Otherside", "artist": "RHCP"})

_apple_name, _apple_structured = _apple_playlist_from_scripts([
    "not-json",
    __import__("json").dumps(sample),
])
check("apple structured extractor: playlist name + ordered songs",
      _apple_name == "My PL" and _apple_structured == [
          {"title": "Otherside", "artist": "RHCP"},
          {"title": "Scar Tissue", "artist": "RHCP"},
      ])

_duplicate_sample = {"data": [{"type": "playlists", "attributes": {"name": "Loop"},
                     "relationships": {"tracks": {"data": [
                         {"type": "songs", "attributes": {
                             "name": "Again", "artistName": "Artist"}},
                         {"type": "songs", "attributes": {
                             "name": "Again", "artistName": "Artist"}},
                     ]}}}]}
_duplicate_name, _duplicate_tracks = _apple_playlist_from_scripts([
    __import__("json").dumps(_duplicate_sample)])
check("apple structured extractor preserves intentional duplicate positions",
      _duplicate_name == "Loop" and len(_duplicate_tracks) == 2)

# Spotify and Deezer importers parse public metadata only; downloads still use lucida.
_spotify_obj = {
    "props": {"pageProps": {"state": {"data": {"entity": {
        "type": "playlist", "name": "My Spotify Mix", "trackList": [
            {"entityType": "track", "title": "One", "subtitle": "Artist\xa0A"},
            {"entityType": "episode", "title": "Podcast", "subtitle": "Host"},
            {"entityType": "track", "title": "One", "subtitle": "Artist\xa0A"},
        ],
    }}}}},
}
_spotify_html = ('<script id="__NEXT_DATA__" type="application/json">'
                 + __import__("json").dumps(_spotify_obj) + '</script>')
_spotify_name, _spotify_tracks = _spotify_playlist_from_html(_spotify_html)
check("spotify extractor keeps order/duplicates and skips episodes",
      _spotify_name == "My Spotify Mix"
      and _spotify_tracks == [
          {"title": "One", "artist": "Artist A"},
          {"title": "One", "artist": "Artist A"},
      ])
_spotify_ld = ('<script type="application/ld+json">'
               + __import__("json").dumps({
                   "description": "Playlist · Top Hits 2026 · 198 items · 2 saves"})
               + '</script>')
check("spotify extractor detects playlists beyond the public 100-item window",
      _spotify_total_from_html(_spotify_ld) == 198)

_deezer_name, _deezer_tracks, _deezer_next = _deezer_playlist_from_obj({
    "title": "My Deezer Mix",
    "tracks": {"data": [
        {"title": "First", "artist": {"name": "Primary"},
         "contributors": [{"name": "Primary"}, {"name": "Guest"}]},
        {"title": "Again", "artist": {"name": "Primary"}},
    ], "next": "https://api.deezer.com/next"},
})
check("deezer extractor keeps order, contributors and pagination",
      _deezer_name == "My Deezer Mix"
      and _deezer_tracks == [
          {"title": "First", "artist": "Primary, Guest"},
          {"title": "Again", "artist": "Primary"},
      ] and _deezer_next.endswith("/next"))

_tidal_html = """<h1><a>My TIDAL Mix</a></h1>
<list-item product-type="track"><span slot="title">First &amp; Last</span>
<span slot="artist"><a>Primary</a><a>Guest</a></span></list-item>
<list-item product-type="track"><span slot="title">Again</span>
<span slot="artist"><a>Primary</a></span></list-item>"""
_tidal_name, _tidal_tracks = _tidal_playlist_from_html(_tidal_html)
check("tidal embed extractor keeps order and separates artists",
      _tidal_name == "My TIDAL Mix" and _tidal_tracks == [
          {"title": "First & Last", "artist": "Primary, Guest"},
          {"title": "Again", "artist": "Primary"},
      ])

_tidal_page, _tidal_total, _tidal_read, _tidal_skipped = _tidal_items_from_obj({
    "totalNumberOfItems": 2,
    "items": [
        {"type": "track", "item": {"title": "Song", "version": "Live",
         "artists": [{"name": "One"}, {"name": "Two"}]}},
        {"type": "video", "item": {"title": "Interview"}},
    ],
})
check("tidal full extractor counts positions and skips videos explicitly",
      _tidal_page == [{"title": "Song (Live)", "artist": "One, Two"}]
      and (_tidal_total, _tidal_read, _tidal_skipped) == (2, 2, 1))

_amazon_name, _amazon_tracks = _amazon_playlist_from_html("""
<h1>Amazon Mix</h1><div>2 SONGS</div>
<music-image-row index="1" primary-text="One's" secondary-text-1="Artist A"
 primary-href="/albums/a?trackAsin=1">
<music-image-row index="2" primary-text="One's" secondary-text-1="Artist A"
 primary-href="/albums/a?trackAsin=1">
""")
check("amazon extractor validates count and preserves duplicate positions",
      _amazon_name == "Amazon Mix" and len(_amazon_tracks) == 2
      and _amazon_tracks[0] == _amazon_tracks[1])

_qobuz_name, _qobuz_tracks, _qobuz_total, _qobuz_read = _qobuz_playlist_from_obj({
    "name": "Qobuz Mix", "tracks_count": 1,
    "tracks": {"total": 1, "items": [{
        "title": "A Song", "version": "Acoustic",
        "performer": {"name": "An Artist"},
    }]},
})
check("qobuz extractor reads public API metadata and versions",
      _qobuz_name == "Qobuz Mix"
      and _qobuz_tracks == [{"title": "A Song (Acoustic)", "artist": "An Artist"}]
      and (_qobuz_total, _qobuz_read) == (1, 1))

# State dedup
import tempfile
p = _os.path.join(tempfile.gettempdir(), "lucidadl_selftest_state.json")
if _os.path.exists(p):
    _os.remove(p)
st = utils.State(p)
check("state empty", not st.has("u1"))
check("reserve first ok", st.reserve("u1") is True)
check("reserve second blocked (in-flight)", st.reserve("u1") is False)
st.add("u1")
check("state remembers", st.has("u1") and utils.State(p).has("u1"))
check("reserve blocked after done", st.reserve("u1") is False)
check("reserve other ok + release", st.reserve("u2") and (st.release("u2") or st.reserve("u2")))
_os.remove(p)

# dedup scoped to a destination folder (playlist) + multi-path per URL
import shutil as _sh0
_d3 = tempfile.mkdtemp(prefix="lucidadl_state2_")
_sp = _os.path.join(_d3, "state.json")
_artists = _os.path.join(_d3, "Artists", "Sinyo", "Enfant Perdu")
_pls = _os.path.join(_d3, "Playlists", "saddd")
_os.makedirs(_artists); _os.makedirs(_pls)
_af = _os.path.join(_artists, "Enfant Perdu.flac"); open(_af, "w").write("x")
s3 = utils.State(_sp)
s3.add("urlE", _af)                                  # downloaded standalone into Artists/
check("scoped: present anywhere counts unscoped", s3.has("urlE"))
check("scoped: NOT done for a playlist folder it's missing from",
      not s3.has("urlE", under=_pls))
check("scoped: reserve succeeds to fetch it into the playlist",
      s3.reserve("urlE", under=_pls))
s3.release("urlE")
_pf = _os.path.join(_pls, "Enfant Perdu.flac"); open(_pf, "w").write("y")
s3.add("urlE", _pf)                                  # now also in the playlist folder
check("scoped: done once present in the playlist folder", s3.has("urlE", under=_pls))
check("multi-path persisted", sorted(utils.State(_sp).done["urlE"]) == sorted([_af, _pf]))
s3.done["urlLegacy"] = []                            # legacy entry, no recorded path
check("legacy unscoped = done", s3.has("urlLegacy"))
check("legacy scoped = re-download", not s3.has("urlLegacy", under=_pls))
_os.remove(_pf)
check("deleted playlist copy -> not done for that playlist", not s3.has("urlE", under=_pls))
s3.done["gone"] = [_os.path.join(_d3, "missing.flac")]
_removed_paths, _removed_items = s3.prune()
check("state prune removes missing paths/items",
      _removed_paths == 2 and _removed_items == 1 and "gone" not in s3.done
      and s3.done.get("urlE") == [_af])
check("state prune preserves unverifiable legacy entries", "urlLegacy" in s3.done)
_sh0.rmtree(_d3, ignore_errors=True)

# organize: album_dir + zip extraction/placement (no real tags -> Unknown)
from lucidadl import organize as _org
ad = _org.album_dir("/music", {"albumartist": "RHCP", "album": "Cal"})
check("album_dir uses albumartist", ad.replace("\\", "/").endswith("/music/RHCP/Cal"))
ad2 = _org.album_dir("/music", {})
check("album_dir unknown fallback", "Unknown Artist" in ad2 and "Unknown Album" in ad2)

import zipfile as _zip
import shutil as _sh
_d = tempfile.mkdtemp(prefix="lucidadl_org_")
_zp = _os.path.join(_d, "album.zip")
with _zip.ZipFile(_zp, "w") as z:
    z.writestr("01 - Song.flac", b"not a real flac")
    z.writestr("cover.jpg", b"img")
_finals = _org.process_download(_zp, _d)
check("zip extracted 1 audio", len(_finals) == 1 and _finals[0].endswith(".flac"))
check("placed under Unknown Artist", "Unknown Artist" in _finals[0])
check("source zip removed", not _os.path.exists(_zp))
check("cover placed next to track", _os.path.exists(_os.path.join(_os.path.dirname(_finals[0]), "cover.jpg")))
_sh.rmtree(_d, ignore_errors=True)

# organize: API-metadata fallback (used only when embedded tags are missing)
check("mutagen_available is bool", isinstance(_org.mutagen_available(), bool))
# embedded tags WIN over meta
_ad = _org.album_dir("/m", {"albumartist": "RHCP", "album": "Cal"},
                     {"albumartist": "MetaAA", "album": "MetaAlb"})
check("album_dir: embedded tags win over meta", _ad.replace("\\", "/").endswith("/m/RHCP/Cal"))
# meta FILLS BLANKS when tags absent
_ad = _org.album_dir("/m", {}, {"albumartist": "Daft Punk", "album": "Discovery"})
check("album_dir: meta fills blank tags", _ad.replace("\\", "/").endswith("/m/Daft Punk/Discovery"))
# CRITICAL regression: embedded `artist` (blank albumartist) must NOT be relocated by meta albumartist
_ad = _org.album_dir("/m", {"artist": "RealArtist"}, {"albumartist": "MetaAA", "album": "X"})
check("album_dir: embedded artist not overridden by meta albumartist",
      _ad.replace("\\", "/").endswith("/m/RealArtist/X"))
# meta=None unchanged (backward compat)
check("album_dir: meta=None unchanged",
      _org.album_dir("/m", {"album": "Y"}).replace("\\", "/").endswith("/m/Unknown Artist/Y"))

# place_file / process_download thread meta; collection still wins
_d2 = tempfile.mkdtemp(prefix="lucidadl_meta_")
def _junk(name):
    p = _os.path.join(_d2, name)
    with open(p, "wb") as fh:
        fh.write(b"not a real flac")
    return p
_pf = _org.place_file(_junk("a.flac"), _d2, meta={"albumartist": "Daft Punk", "album": "Discovery"})
check("place_file: album under Artists/<Artist>/<Album> via meta",
      _os.path.dirname(_pf).replace("\\", "/").endswith("/Artists/Daft Punk/Discovery"))
_pf = _org.place_file(_junk("b.flac"), _d2, collection="MyMix",
                      meta={"albumartist": "Daft Punk", "album": "Discovery"})
check("place_file: playlist under Playlists/<name> (collection beats meta)",
      _os.path.dirname(_pf).replace("\\", "/").endswith("/Playlists/MyMix"))
_pf = _org.process_download(_junk("c.flac"), _d2, None, {"albumartist": "AA", "album": "BB"})[0]
check("process_download threads meta", _os.path.dirname(_pf).replace("\\", "/").endswith("/AA/BB"))
# zip + meta
_zp2 = _os.path.join(_d2, "alb.zip")
with _zip.ZipFile(_zp2, "w") as z:
    z.writestr("01 - Song.flac", b"x")
_zf = _org.process_download(_zp2, _d2, None, {"albumartist": "CompAA", "album": "Cal"})
check("zip + meta -> album folder", _os.path.dirname(_zf[0]).replace("\\", "/").endswith("/CompAA/Cal"))
# audio-less zip: process_download returns [] (downloader treats [] as a failure, not
# a bogus success on the deleted zip path) and the source zip is still removed
_zp3 = _os.path.join(_d2, "noaudio.zip")
with _zip.ZipFile(_zp3, "w") as z:
    z.writestr("cover.jpg", b"img")
    z.writestr("notes.txt", b"hello")
_zf3 = _org.process_download(_zp3, _d2)
check("audio-less zip -> [] (no false success)", _zf3 == [])
check("audio-less zip still removed", not _os.path.exists(_zp3))
_sh.rmtree(_d2, ignore_errors=True)

# filename cleanup: strip the artist; number playlist tracks to keep order
_d4 = tempfile.mkdtemp(prefix="lucidadl_name_")
def _mk(_n):
    _p = _os.path.join(_d4, _n)
    with open(_p, "wb") as _fh:
        _fh.write(b"x")
    return _p
_pf = _org.place_file(_mk("Daft Punk - Aerodynamic.flac"), _d4,
                      meta={"artist": "Daft Punk", "album": "Discovery", "title": "Aerodynamic"})
check("filename: artist stripped via API title", _os.path.basename(_pf) == "Aerodynamic.flac")
_pf = _org.place_file(_mk("Sinyo - Enfant Perdu.flac"), _d4, collection="saddd",
                      meta={"artist": "Sinyo", "title": "Enfant Perdu"}, track_no="07")
check("filename: playlist track numbered + artist stripped",
      _os.path.basename(_pf) == "07 - Enfant Perdu.flac")
_t, _e = _org._title_and_ext("Black Sabbath - Iron Man (2012 - Remaster).flac",
                             {"artist": "Black Sabbath"}, prefer_meta_title=False)
check("title: strip artist prefix but keep ' - ' inside the title",
      _t == "Iron Man (2012 - Remaster)" and _e == ".flac")
_t2, _ = _org._title_and_ext("Iron Man (2012 - Remaster).flac", {}, prefer_meta_title=False)
check("title: no artist match -> keep stem (no false ' - ' strip)",
      _t2 == "Iron Man (2012 - Remaster)")
_sh.rmtree(_d4, ignore_errors=True)

# tracknumber fix: 'N/M' composite embedded tags are rewritten to the bare number
check("bare track number: fraction", _org._bare_track_number("6/12") == "6")
check("bare track number: spaced fraction", _org._bare_track_number(" 6 / 12 ") == "6")
check("bare track number: already bare -> None", _org._bare_track_number("6") is None)
check("bare track number: empty -> None", _org._bare_track_number("") is None)
check("bare track number: not a pair -> None",
      _org._bare_track_number("A/12") is None and _org._bare_track_number("6/12/13") is None)

if _org.mutagen_available():
    from mutagen import File as _mFile
    from unittest.mock import patch as _tag_patch
    _d6 = tempfile.mkdtemp(prefix="lucidadl_trackno_")

    def _tagged_flac(name, tracknumber):
        """A minimal but mutagen-readable FLAC (magic + STREAMINFO, no audio frames)."""
        p = _os.path.join(_d6, name)
        info = (4096).to_bytes(2, "big") * 2 + bytes(6) \
            + ((44100 << 44) | (1 << 41) | (15 << 36)).to_bytes(8, "big") + bytes(16)
        with open(p, "wb") as fh:
            fh.write(b"fLaC" + bytes([0x80]) + (34).to_bytes(3, "big") + info)
        tf = _mFile(p, easy=True)
        tf["tracknumber"] = tracknumber
        tf.save()
        return p

    _fp = _org.place_file(_tagged_flac("t1.flac", "6/12"), _d6,
                          meta={"albumartist": "AA", "album": "BB"})
    check("tracknumber fix: '6/12' -> '6' on the placed file",
          list(_mFile(_fp, easy=True).get("tracknumber") or []) == ["6"])
    _fp2 = _org.place_file(_tagged_flac("t2.flac", "3"), _d6,
                           meta={"albumartist": "AA", "album": "BB"})
    check("tracknumber fix: already-bare value left untouched",
          list(_mFile(_fp2, easy=True).get("tracknumber") or []) == ["3"])

    # A real partial write must only damage the disposable copy, never the download.
    _fp3 = _tagged_flac("partial.flac", "6/12")
    with open(_fp3, "rb") as _fh:
        _original = _fh.read()
    _entries_before = set(_os.listdir(_d6))

    def _partial_tag_save(self, filename=None, **kwargs):
        with open(filename or self.filename, "r+b") as fh:
            fh.write(b"broken")
        raise OSError("simulated partial metadata write")

    with _tag_patch.object(type(_mFile(_fp3, easy=True)), "save",
                           autospec=True, side_effect=_partial_tag_save) as _save:
        _org.fix_track_number(_fp3)
    check("tracknumber fix: partial write failure was exercised", _save.call_count == 1)
    with open(_fp3, "rb") as _fh:
        check("tracknumber fix: partial write preserves original bytes",
              _fh.read() == _original)
    check("tracknumber fix: partial write leaves no temporary file",
          set(_os.listdir(_d6)) == _entries_before)

    _fp4 = _tagged_flac("replace.flac", "6/12")
    with open(_fp4, "rb") as _fh:
        _original = _fh.read()
    _entries_before = set(_os.listdir(_d6))
    with _tag_patch.object(_org.os, "replace", side_effect=OSError("file locked")) as _replace:
        _org.fix_track_number(_fp4)
    check("tracknumber fix: replacement failure was exercised", _replace.call_count == 1)
    with open(_fp4, "rb") as _fh:
        check("tracknumber fix: replacement failure preserves original bytes",
              _fh.read() == _original)
    check("tracknumber fix: replacement failure leaves no temporary file",
          set(_os.listdir(_d6)) == _entries_before)

    def _partial_tag_copy(src, dst):
        with open(dst, "wb") as fh:
            fh.write(b"incomplete copy")
        raise OSError("simulated disk full")

    with _tag_patch.object(_org.shutil, "copy2", side_effect=_partial_tag_copy) as _copy:
        _org.fix_track_number(_fp4)
    check("tracknumber fix: copy failure was exercised", _copy.call_count == 1)
    with open(_fp4, "rb") as _fh:
        check("tracknumber fix: copy failure preserves original bytes",
              _fh.read() == _original)
    check("tracknumber fix: copy failure leaves no temporary file",
          set(_os.listdir(_d6)) == _entries_before)

    _org.fix_track_number(_fp4)
    check("tracknumber fix: successful retry saves the bare number and cleans up",
          list(_mFile(_fp4, easy=True).get("tracknumber") or []) == ["6"]
          and set(_os.listdir(_d6)) == _entries_before)
    _sh.rmtree(_d6, ignore_errors=True)

# playlist .m3u8 sidecar: lists audio in track order, bare filenames, with EXTINF titles
_d5 = tempfile.mkdtemp(prefix="lucidadl_m3u_")
_plf = _os.path.join(_d5, "Playlists", "My Mix")
_os.makedirs(_plf)
for _n in ("02 - Beta.m4a", "01 - Alpha.flac", "cover.jpg"):
    with open(_os.path.join(_plf, _n), "wb") as _fh:
        _fh.write(b"x")
_m3u = _org.write_playlist_m3u(_d5, "My Mix")
check("m3u8: named after the playlist, inside its folder",
      _m3u and _os.path.basename(_m3u) == "My Mix.m3u8"
      and _os.path.dirname(_m3u) == _plf)
with open(_m3u, encoding="utf-8") as _fh:
    _body = _fh.read()
_audio_lines = [ln for ln in _body.splitlines() if not ln.startswith("#")]
check("m3u8: tracks in filename order, bare names, no cover.jpg",
      _audio_lines == ["01 - Alpha.flac", "02 - Beta.m4a"])
check("m3u8: header + EXTINF with number-prefix stripped",
      _body.startswith("#EXTM3U") and "#EXTINF:-1,Alpha" in _body
      and "#EXTINF:-1,Beta" in _body)
check("m3u8: empty folder -> None (no file written)",
      _org.write_playlist_m3u(_d5, "Nope") is None)
check("_m3u_title strips 'NN - ' prefix and extension",
      _org._m3u_title("07 - Enfant Perdu.m4a") == "Enfant Perdu"
      and _org._m3u_title("No Prefix.flac") == "No Prefix")
check("m3u8 numeric ordering survives mixed zero-padding",
      sorted(["100 - Last.flac", "02 - Second.flac", "005 - Fifth.flac"],
             key=_org._playlist_sort_key) ==
      ["02 - Second.flac", "005 - Fifth.flac", "100 - Last.flac"])
_sh.rmtree(_d5, ignore_errors=True)

# A downloaded track whose title contains a dot keeps its audio extension, so the
# playlist sidecar still lists it instead of silently dropping the track.
_d7 = tempfile.mkdtemp(prefix="lucidadl_dotted_")
_plf2 = _os.path.join(_d7, "Playlists", "Dotted")
_os.makedirs(_plf2)
_dotted = utils.sanitize_filename("03 - Song. Extended Version Here.flac")
with open(_os.path.join(_plf2, _dotted), "wb") as _fh:
    _fh.write(b"x")
_m3u2 = _org.write_playlist_m3u(_d7, "Dotted")
check("m3u8: a dotted track name keeps its extension and stays listed",
      _dotted == "03 - Song. Extended Version Here.flac" and _m3u2
      and "03 - Song. Extended Version Here.flac"
      in open(_m3u2, encoding="utf-8").read())
_sh.rmtree(_d7, ignore_errors=True)

# downloader meta builders
from lucidadl.downloader import _track_meta as _tm, _join_artists as _ja
check("_join_artists None -> ''", _ja(None) == "")
check("_join_artists skips nameless", _ja([{"name": "X"}, {"foo": 1}]) == "X")
_m_alb = _tm({"title": "Californication", "artists": [{"name": "RHCP"}]},
             {"title": "Around the World", "artists": [{"name": "RHCP"}]}, True)
check("_track_meta album: album-level artist + album title",
      _m_alb == {"albumartist": "RHCP", "album": "Californication", "artist": "RHCP",
                 "title": "Around the World"})
# compilation: album-level artist used for ALL tracks (no per-track scatter)
_m_va = _tm({"title": "VA Comp", "artists": [{"name": "Various Artists"}]},
            {"title": "Song", "artists": [{"name": "Some Performer"}]}, True)
check("_track_meta album: uses album artist, not per-track (no scatter)",
      _m_va["albumartist"] == "Various Artists")
_m_sgl = _tm({}, {"title": "One More Time", "artists": [{"name": "Daft Punk"}],
                  "album": {"title": "Discovery"}}, False)
check("_track_meta single: track artist + nested album.title",
      _m_sgl["albumartist"] == "Daft Punk" and _m_sgl["album"] == "Discovery")

from lucidadl import tui as _tui

# matching: pick the real track over remixes / the real album over tributes
from lucidadl import matching as _m
_tracks = [
    {"url": "remix1", "title": "Do I Wanna Know? (Lncn Remix)", "context": "Do I Wanna Know? (Lncn Remix) Arctic Monkeys"},
    {"url": "remix2", "title": "Do I Wanna Know? (Club Mix)", "context": "Do I Wanna Know? (Club Mix) Arctic Monkeys"},
    {"url": "real", "title": "Do I Wanna Know?", "context": "Do I Wanna Know? Arctic Monkeys AM"},
]
check("match picks real track over remixes",
      _m.pick_best("Arctic Monkeys - Do I Wanna Know?", _tracks) == "real")

_albums = [
    {"url": "trib", "title": "Tribute to Red Hot Chili Peppers", "context": "Tribute to Red Hot Chili Peppers Various Artists"},
    {"url": "rend", "title": "Lullaby Renditions of Red Hot Chili Peppers", "context": "Lullaby Renditions Rockabye Baby"},
    {"url": "realalb", "title": "Californication", "context": "Californication Red Hot Chili Peppers 1999"},
]
check("match picks real album over tribute/renditions",
      _m.pick_best("Red Hot Chili Peppers - Californication", _albums) == "realalb")

check("match: explicit remix query keeps remix",
      _m.pick_best("Artist - Song Remix", [
          {"url": "r", "title": "Song Remix", "context": "Song Remix Artist"},
          {"url": "p", "title": "Song", "context": "Song Artist"}]) in ("r", "p"))
check("match empty -> None", _m.pick_best("x", []) is None)

# matching: pick the real artist's album over a same-titled cover/tribute
alb_candidates = [
    {"url": "u_cover", "title": "Californication", "artist": "ReStyleHits", "album": ""},
    {"url": "u_tribute", "title": "Californication", "artist": "Vitamin String Quartet", "album": ""},
    {"url": "u_rhcp", "title": "Californication", "artist": "Red Hot Chili Peppers", "album": ""},
]
check("matching: real artist album beats cover",
      matching.pick_best("Red Hot Chili Peppers - Californication", alb_candidates) == "u_rhcp")

# matching: pick the real track over remixes
trk_candidates = [
    {"url": "t_rmx1", "title": "Otherside (Moonbeam Remix)", "artist": "Red Hot Chili Peppers"},
    {"url": "t_rmx2", "title": "Otherside (Club Mix)", "artist": "DJ X"},
    {"url": "t_real", "title": "Otherside", "artist": "Red Hot Chili Peppers"},
]
check("matching: real track beats remixes",
      matching.pick_best("Red Hot Chili Peppers - Otherside", trk_candidates) == "t_real")

# matching: wrong artist penalised even with exact title
check("matching: wrong artist loses",
      matching.pick_best("Red Hot Chili Peppers - Otherside",
                         [{"url": "w", "title": "Otherside", "artist": "Macklemore"},
                          {"url": "r", "title": "Otherside", "artist": "Red Hot Chili Peppers"}]) == "r")
check("matching: automatic mode rejects a wrong-artist-only result",
      matching.pick_best("Red Hot Chili Peppers - Otherside",
                         [{"url": "w", "title": "Otherside", "artist": "Macklemore"}],
                         min_score=5.5, min_margin=0.25) is None)
check("matching: automatic mode rejects tied editions",
      matching.pick_best("Artist - Song",
                         [{"url": "a", "title": "Song", "artist": "Artist"},
                          {"url": "b", "title": "Song", "artist": "Artist"}],
                         min_score=5.5, min_margin=0.25) is None)
check("matching: automatic mode rejects a secondary-artist cover",
      matching.pick_best(
          "Red Hot Chili Peppers - Under the Bridge",
          [{"url": "cover", "title": "Under The Bridge",
            "artist": "Rhythms Del Mundo, Red Hot Chili Peppers"}],
          min_score=5.5, min_margin=0.25) is None)
check("matching: automatic mode rejects an unrequested sped-up version",
      matching.pick_best(
          "Manu Chao - Bongo Bong",
          [{"url": "sped", "title": "Bongo Bong - Sped Up (Manu Chao)",
            "artist": "Manu Chao, spedup trends"}],
          min_score=5.5, min_margin=0.25) is None)
check("matching: automatic mode accepts a matching primary artist",
      matching.pick_best(
          "La Fine Equipe, Saneyes - Lying With You",
          [{"url": "right", "title": "Lying With You", "artist": "La Fine Equipe"}],
          min_score=5.5, min_margin=0.25) == "right")

# resolver query variants (specific -> loose) + artist-gated broadening
from lucidadl.downloader import _query_variants as _qv
_v = _qv("Sinyo' - Enfant Perdu")
check("variants: full query first", _v[0] == "Sinyo' - Enfant Perdu")
check("variants: title-only included", "Enfant Perdu" in _v)
_v2 = _qv("Ptite Soeur, FEMTOGO - PUKE SOMETHING")
check("variants: title-only + primary-artist forms",
      "PUKE SOMETHING" in _v2 and "Ptite Soeur PUKE SOMETHING" in _v2)
check("variants: no separator -> just the line", _qv("Madonna") == ["Madonna"])

from lucidadl.downloader import friendly_error as _friendly_error
check("friendly error: access guidance", "lucida setup" in _friendly_error(Exception("HTTP 403")))
check("friendly error: timeout retry guidance", "safe to retry" in _friendly_error(Exception("timed out")))

from lucidadl.downloader import _playlist_download_key, _existing_playlist_copy
_legacy_playlist_dir = tempfile.mkdtemp(prefix="lucidadl_playlist_state_")
_legacy_file = _os.path.join(_legacy_playlist_dir, "02 - Song.flac")
with open(_legacy_file, "wb") as _handle:
    _handle.write(b"x")
_legacy_state = utils.State(_os.path.join(_legacy_playlist_dir, "state.json"))
_legacy_state.add("track-url", _legacy_file)
check("playlist state: each duplicate position gets a distinct key",
      _playlist_download_key("track-url", "Mix", "02") !=
      _playlist_download_key("track-url", "Mix", "07"))
check("playlist state: v1.1 copy recognized only at its original position",
      _existing_playlist_copy(_legacy_state, "track-url", _legacy_playlist_dir, "02") ==
      _legacy_file and
      not _existing_playlist_copy(_legacy_state, "track-url", _legacy_playlist_dir, "07"))
_sh0.rmtree(_legacy_playlist_dir, ignore_errors=True)

from lucidadl.downloader import preview_tracks as _preview_tracks
from lucidadl.downloader import _resolve_targets as _resolve_targets
from lucidadl.api import LucidaError as _LucidaError

class _AmazonRegionClient:
    def __init__(self, successful_country, invalid_page=None):
        self.successful_country = successful_country
        self.invalid_page = invalid_page
        self.countries = []

    async def fetch_page_data(self, url, region):
        self.countries.append(region)
        if region != self.successful_country:
            if self.invalid_page is not None:
                return self.invalid_page
            raise _LucidaError("territory unavailable")
        return {"info": {"type": "track", "url": url, "title": "Song",
                          "producers": ["p"]},
                "token": "token", "tokenExpiry": 1}

    tracks_from_pd = staticmethod(LucidaClient.tracks_from_pd)

_amazon_regions = _AmazonRegionClient("GB")
_amazon_targets = _aio.run(_resolve_targets(
    _amazon_regions, "https://music.amazon.co.uk/tracks/123", "track",
    "qobuz", "US", False, lambda *_: None))
check("Amazon region fallback: auto, US, then GB; target keeps resolved country",
      _amazon_regions.countries == ["", "US", "GB"]
      and _amazon_targets and _amazon_targets[0].get("country") == "GB"
      and _amazon_targets[0].get("csrf") == "token")

_amazon_auto = _AmazonRegionClient("")
_auto_targets = _aio.run(_resolve_targets(
    _amazon_auto, "https://music.amazon.com/tracks/123", "track",
    "amazon", None, False, lambda *_: None))
check("Amazon region fallback stops after automatic resolution succeeds",
      _amazon_auto.countries == [""] and _auto_targets[0]["country"] == "")

for _invalid_page in ({"info": {}}, {
        "info": {"type": "track", "url": "https://music.amazon.com/tracks/123"},
        "tokenExpiry": 1}):
    _amazon_jp = _AmazonRegionClient("JP", _invalid_page)
    _jp_targets = _aio.run(_resolve_targets(
        _amazon_jp, "https://music.amazon.co.jp/tracks/123", "track",
        "qobuz", "US", False, lambda *_: None))
    check("Amazon fallback rejects parsed pages without a usable track/token",
          _amazon_jp.countries == ["", "US", "GB", "JP"]
          and _jp_targets[0]["country"] == "JP")

_amazon_failed = _AmazonRegionClient(None)
try:
    _aio.run(_resolve_targets(
        _amazon_failed, "https://music.amazon.com/tracks/123", "track",
        "amazon", "US", False, lambda *_: None))
except _LucidaError as _region_error:
    check("Amazon fallback raises after all regions fail",
          _amazon_failed.countries == ["", "US", "GB", "JP"]
          and str(_region_error) == "territory unavailable")
else:
    check("Amazon fallback raises after all regions fail", False)

_qobuz_client = _AmazonRegionClient("US")
_qobuz_targets = _aio.run(_resolve_targets(
    _qobuz_client, "https://play.qobuz.com/track/123", "track",
    "amazon", "US", False, lambda *_: None))
check("Direct Qobuz URL keeps its country even with Amazon preferred",
      _qobuz_client.countries == ["US"] and "country" not in _qobuz_targets[0])

# Exercise the handoff without making requests or creating audio files.
from unittest.mock import AsyncMock as _AsyncMock, Mock as _Mock
from lucidadl.downloader import _download_target
for _target, _expected_country in ((_amazon_targets[0], "GB"),
                                    (_auto_targets[0], ""),
                                    (_qobuz_targets[0], "US")):
    _handoff_client = _Mock()
    _handoff_client.start_download = _AsyncMock(return_value=("handoff", "server"))
    _handoff_client.run_job = _AsyncMock(return_value=__file__)
    _aio.run(_download_target(
        _handoff_client, _Mock(), _target, "US", _os.getcwd(), False, False,
        None, _Mock(), {"ok": 0, "skip": 0, "fail": 0}, [], _aio.Lock()))
    check("Download handoff preserves resolved country " + repr(_expected_country),
          _handoff_client.start_download.await_args.args[2] == _expected_country)

class _PreviewClient:
    async def search(self, query, _service):
        if "Missing" in query:
            return {"tracks": []}
        title = query.split(" - ", 1)[-1]
        return {"tracks": [{"url": "https://qobuz/" + title, "title": title,
                            "artist": "Artist", "context": title + " Artist"}]}

    async def fetch_page_data(self, url, _country):
        title = url.rsplit("/", 1)[-1]
        return {"info": {"type": "track", "url": url, "title": title,
                         "artists": [{"name": "Artist"}], "producers": ["p"]},
                "token": "token", "tokenExpiry": 1}

    tracks_from_pd = staticmethod(LucidaClient.tracks_from_pd)

_preview = _aio.run(_preview_tracks(
    _PreviewClient(), ["Artist - One", "Artist - Missing", "Artist - Two"],
    "qobuz", "US", jobs=3, log=lambda *_: None))
check("playlist check: preserves order and reports missing matches",
      [row["index"] for row in _preview] == [1, 2, 3]
      and [row["status"] for row in _preview] == ["matched", "not found", "matched"])

_title_hits = [
    {"url": "wrong", "title": "Enfant Perdu", "artist": "Some Other Artist", "context": "Enfant Perdu Some Other Artist"},
    {"url": "right", "title": "Enfant Perdu", "artist": "Sinyo", "context": "Enfant Perdu Sinyo"},
]
check("require_artist picks the matching artist from a title-only search",
      matching.pick_best("Sinyo' - Enfant Perdu", _title_hits, require_artist=True) == "right")
_only_wrong = [{"url": "w", "title": "Enfant Perdu", "artist": "Nope", "context": "Enfant Perdu Nope"}]
check("require_artist returns None when no artist matches (no wrong download)",
      matching.pick_best("Sinyo' - Enfant Perdu", _only_wrong, require_artist=True) is None)
check("require_artist off -> legacy best-anyway behavior",
      matching.pick_best("Sinyo' - Enfant Perdu", _only_wrong) == "w")
check("artist_matches checks the primary artist",
      matching.artist_matches("Sinyo' - Enfant Perdu", {"artist": "Sinyo"}) is True
      and matching.artist_matches("Sinyo' - Enfant Perdu", {"artist": "Other"}) is False)

# transcode bitrate normalization (bare number = kbps)
from lucidadl import transcode as _T
check("bitrate 192 -> 192k", _T.norm_bitrate("192") == "192k")
check("bitrate 320k stays", _T.norm_bitrate("320k") == "320k")
check("bitrate None stays None", _T.norm_bitrate(None) is None)
check("transcode cmd has -b:a 192k",
      "192k" in _T.build_cmd("ffmpeg", "i.flac", "o.m4a", "aac", "192"))

# fast HTTP path parsing (raw SvelteKit JSON5 blob -> tracks + helpers)
import pyjson5
from lucidadl.api import _between, _filename_from_cd, _download_filename, _retry_delay
_alb = ('{info:{success:true,type:"album",title:"Cal",tracks:['
        '{title:"A",url:"https://q/track/1",csrf:"C1",csrfFallback:"F1",producers:["p"]},'
        '{title:"B",url:"https://q/track/2",csrf:"C2",csrfFallback:null,producers:null}'
        ']},originalService:"qobuz",token:"TOK",tokenExpiry:123}')
_tracks = LucidaClient.tracks_from_pd(pyjson5.loads(_alb))
check("pd album -> 2 tracks w/ csrf", len(_tracks) == 2 and _tracks[0]["csrf"] == "C1")
check("pd album null producers kept", _tracks[1].get("producers") is None)
_encoded_token = "VmxKT01IRkdiblkyVVZWUmJrVk5iVkEzTUZJelVVOXpRV3c0"
_trk = LucidaClient.tracks_from_pd(pyjson5.loads(
    '{info:{type:"track",title:"X",url:"https://q/track/9",producers:["p"]},'
    f'token:"{_encoded_token}",tokenExpiry:9}}'))
check("pd single track token mirrors the UI's double decode",
      len(_trk) == 1 and _trk[0]["csrf"] == "VRN0qFnv6QUQnEMmP70R3QOsAl8")
_legacy_trk = LucidaClient.tracks_from_pd(pyjson5.loads(
    '{info:{type:"track",title:"X",url:"https://q/track/9"},token:"TT"}'))
check("pd single track keeps an unencoded legacy token",
      _legacy_trk[0]["csrf"] == "TT")
check("_between slices blob",
      _between('x,{"type":"data","data":{a:1},"uses":{"url":1}}];y',
               ',{"type":"data","data":', ',"uses":{"url":1}}];') == "{a:1}")
check("filename from content-disposition",
      _filename_from_cd('attachment; filename="01 - Song.flac"') == "01 - Song.flac")
check("download filename keeps a real media extension",
      _download_filename('attachment; filename="01 - Song.flac"', "Song", "flac")
      == "01 - Song.flac")
check("download filename adds the extension to a name that only has a dot",
      _download_filename('attachment; filename="Song. Extended Version Here"',
                         "Song", "flac") == "Song. Extended Version Here.flac")
check("download filename adds the extension when the name has none",
      _download_filename('attachment; filename="Song"', "Song", "flac") == "Song.flac")
check("download filename falls back to the track title without a header",
      _download_filename("", "Song", "flac") == "Song.flac")
check("download filename keeps an album archive",
      _download_filename('attachment; filename="Album.zip"', "Album", "zip")
      == "Album.zip")

class _RetryResponse:
    headers = {"Retry-After": "99"}
check("network retry delay is bounded", _retry_delay(_RetryResponse(), 0) == 30)

# refresh dedup: N concurrent 403-refreshes must call acquire() exactly once
_calls = {"n": 0}
async def _fake_acquire():
    _calls["n"] += 1
    await _aio.sleep(0.01)
    return ("CF" + str(_calls["n"]), "UA")
_c = LucidaClient(cf_clearance="old", user_agent="UA", acquire=_fake_acquire)
async def _refresh_storm():
    await _aio.gather(*[_c._refresh_creds() for _ in range(5)])
_aio.run(_refresh_storm())
check("refresh deduped to 1 browser open", _calls["n"] == 1 and _c.cf == "CF1")

# fallback services remain intentionally small
from lucidadl.api import FALLBACK_SERVICES
check("fallback chain", "qobuz" in FALLBACK_SERVICES and "amazon" in FALLBACK_SERVICES)

# first-run UX: the quick doctor must never open a browser unless --live is requested
import contextlib as _ctxlib
import io as _io
from unittest.mock import AsyncMock as _AsyncMock, patch as _patch
from click.testing import CliRunner as _CliRunner
from lucidadl import cli as _cli

with _patch.object(_cli, "chromium_installed", _AsyncMock(return_value=True)), \
     _patch.object(_cli.transcode, "available", return_value=True), \
     _patch.object(_cli, "load_clearance", return_value=("CF", "UA")), \
     _patch.object(_cli, "_music_health", return_value=(True, "ready")), \
     _patch.object(_cli, "_stale_partials", return_value=[]), \
     _patch.object(_cli, "_load_playlist_run", return_value={}), \
     _patch.object(_cli, "lucida_context") as _browser_ctx:
    _doctor_out = _io.StringIO()
    with _ctxlib.redirect_stdout(_doctor_out):
        _doctor_ok = _aio.run(_cli._doctor(live=False))
check("doctor: quick check succeeds without opening a browser",
      _doctor_ok and not _browser_ctx.called and "not run" in _doctor_out.getvalue())

with _patch.object(_cli, "chromium_installed", _AsyncMock(return_value=False)), \
     _patch.object(_cli, "install_chromium", _AsyncMock(return_value=True)) as _install, \
     _patch.object(_cli, "acquire_clearance", _AsyncMock(return_value=("CF", "UA"))) as _access:
    with _ctxlib.redirect_stdout(_io.StringIO()):
        _setup_ok = _aio.run(_cli._setup())
check("setup: installs a missing browser before preparing access",
      _setup_ok and _install.await_count == 1 and _access.await_count == 1)

# no Cloudflare challenge -> no cf_clearance cookie; the UA alone is still saved
from lucidadl import session as _session

class _NoCookiePage:
    url = _session.LUCIDA + "/"
    async def goto(self, *_args, **_kwargs):
        return type("Response", (), {"ok": True, "status": 200})()
    async def title(self):
        return "Lucida"
    async def content(self):
        return "<html><body>Lucida</body></html>"
    async def evaluate(self, _js):
        return "Mozilla/5.0 HeadlessChrome/130"

class _NoCookieCtx:
    pages = [_NoCookiePage()]
    async def cookies(self, _url):
        return [{"name": "__cf_bm", "value": "x"}]

@_ctxlib.asynccontextmanager
async def _no_cookie_context(**_kw):
    yield _NoCookieCtx()

with _patch.object(_session, "lucida_context", _no_cookie_context), \
     _patch.object(_session, "save_clearance") as _saved:
    _cf, _ua = _aio.run(_session.acquire_clearance())
check("access: unchallenged page saves the UA without a cf_clearance cookie",
      _cf is None and _ua == "Mozilla/5.0 Chrome/130"
      and _saved.call_args.args == (None, "Mozilla/5.0 Chrome/130"))

for _navigation_name, _navigation in (
    ("DNS failure", _AsyncMock(side_effect=_session.PlaywrightError("net::ERR_NAME_NOT_RESOLVED"))),
    ("HTTP error", _AsyncMock(return_value=type("Response", (), {"ok": False, "status": 503})())),
    ("missing response", _AsyncMock(return_value=None)),
):
    with _patch.object(_session, "lucida_context", _no_cookie_context), \
         _patch.object(_NoCookiePage, "goto", _navigation), \
         _patch.object(_session, "save_clearance") as _saved:
        _rejected = False
        try:
            _aio.run(_session.acquire_clearance())
        except (RuntimeError, _session.PlaywrightError):
            _rejected = True
    check(f"access: {_navigation_name} does not save prepared access",
          _rejected and not _saved.called)

with _patch.object(_session, "lucida_context", _no_cookie_context), \
     _patch.object(_NoCookiePage, "goto", _AsyncMock(
         return_value=type("Response", (), {"ok": False, "status": 403})())), \
     _patch.object(_session, "is_challenged", _AsyncMock(side_effect=[True, False])), \
     _patch.object(_session, "save_clearance") as _saved:
    _cf, _ua = _aio.run(_session.acquire_clearance())
check("access: a cleared HTTP 403 challenge still prepares access", _saved.called)

with _patch.object(_tui.os.path, "exists", return_value=False):
    check("tui: empty app data is detected as first run", _tui._is_first_run())
with _patch.object(_tui, "load_clearance", return_value=(None, None)):
    check("tui: corrupt/empty access is not shown as prepared", not _tui._access_ready())
with _patch.object(_tui, "load_clearance", return_value=("CF", "UA")):
    check("tui: complete access is shown as prepared", _tui._access_ready())
with _patch.object(_tui, "load_clearance", return_value=(None, "UA")):
    check("tui: cookie-less access (no challenge) is shown as prepared", _tui._access_ready())

# corrupt or hand-edited settings must not prevent the TUI from starting
with _patch.object(_tui.paths, "load_config", return_value={"jobs": "many"}):
    check("tui: invalid jobs setting falls back safely", _tui._settings()["jobs"] == 3)

# ordinary downloads use the shared runner without depending on playlist-only locals
class _TuiConsole:
    def print(self, *_args, **_kwargs):
        pass


class _TuiCli:
    @staticmethod
    async def _run(*_args, **_kwargs):
        return {"ok": 1, "skip": 0, "fail": 0}, []


def _invoke_tui_go(_s, _console, _cli_obj, _questionary, go):
    go(["Artist - Song"], "track", False)
    return True


with _patch.object(_tui, "_download_action", side_effect=_invoke_tui_go), \
     _patch.object(_tui, "_access_ready", return_value=True), \
     _patch.object(_tui, "_show_run_summary"):
    _tui_download_ok = _tui._dispatch(
        "download",
        {"service": "qobuz", "jobs": 1, "to": None, "bitrate": None,
         "keep_orig": False, "force": False},
        _TuiConsole(), _TuiCli(), object(),
    )
check("tui: ordinary downloads do not depend on playlist choices", _tui_download_ok)

# failures preserve album/track intent, while old files stay backwards-compatible
_failed_dir = tempfile.mkdtemp(prefix="lucidadl_failed_")
_failed_path = _os.path.join(_failed_dir, "failed.txt")
_playlist_run_path = _os.path.join(_failed_dir, "playlist-run.json")
with _patch.object(_cli, "FAILED_PATH", _failed_path), \
     _patch.object(_cli, "PLAYLIST_RUN_PATH", _playlist_run_path):
    _cli._write_failed([("album", "Artist - Album"), ("track", "Artist - Song")])
    check("retry: typed failures round-trip", _cli._read_failed() == [
        FailedItem("album", "Artist - Album"), FailedItem("track", "Artist - Song")])
    _cli._write_failed([
        FailedItem("track", "Artist - Playlist Song", "My Mix", "07")])
    check("retry: playlist context round-trips", _cli._read_failed() == [
        FailedItem("track", "Artist - Playlist Song", "My Mix", "07")])
    with open(_failed_path, "w", encoding="utf-8") as _legacy:
        _legacy.write("Legacy Artist - Song\n")
    check("retry: legacy failures remain track retries",
          _cli._read_failed() == [FailedItem("track", "Legacy Artist - Song")])

    _retry_calls = []
    async def _fake_retry_run(values, kind, *args, **kwargs):
        _retry_calls.append((kind, values))
        if kind == "track":
            return ({"ok": 0, "skip": 0, "fail": 1}, [FailedItem("track", values[0])])
        return ({"ok": 1, "skip": 0, "fail": 0}, [])

    with _patch.object(_cli, "_run", side_effect=_fake_retry_run):
        with _ctxlib.redirect_stdout(_io.StringIO()):
            _retry_result = _aio.run(_cli._retry(
                [("album", "Artist - Album"), ("track", "Artist - Song")],
                "qobuz", None, "original", _failed_dir, False, 3))
    check("retry: albums and tracks are dispatched with their original type",
          _retry_calls == [
              ("album", ["Artist - Album"]), ("track", ["Artist - Song"])])
    check("retry: only unresolved items remain",
          _retry_result[1] == [FailedItem("track", "Artist - Song")]
          and _cli._read_failed() == [FailedItem("track", "Artist - Song")])

    _playlist_retry = []
    async def _fake_playlist_retry(values, kind, *args, **kwargs):
        _playlist_retry.append((values, kind, kwargs))
        return ({"ok": 1, "skip": 0, "fail": 0}, [])

    with _patch.object(_cli, "_run", side_effect=_fake_playlist_retry):
        with _ctxlib.redirect_stdout(_io.StringIO()):
            _aio.run(_cli._retry(
                [FailedItem("track", "Artist - Song", "My Mix", "07")],
                "qobuz", None, "original", _failed_dir, False, 3))
    check("retry: playlist stays in its collection with original number",
          len(_playlist_retry) == 1
          and _playlist_retry[0][2].get("collection") == "My Mix"
          and _playlist_retry[0][2].get("track_numbers") == ["07"])

    _interrupted = {
        "status": "running", "collection": "Interrupted Mix",
        "tracks": [
            {"track_no": "01", "query": "Artist - One"},
            {"track_no": "02", "query": "Artist - Two"},
        ],
        "options": {"service": "amazon", "out": _failed_dir, "jobs": 5},
    }
    _cli._save_playlist_run(_interrupted)
    _resume_calls = []
    async def _fake_resume(values, kind, *args, **kwargs):
        _resume_calls.append((values, kind, args, kwargs))
        return ({"ok": 1, "skip": 1, "fail": 0}, [])
    with _patch.object(_cli, "_run", side_effect=_fake_resume):
        with _ctxlib.redirect_stdout(_io.StringIO()):
            _aio.run(_cli._resume_playlist_run(_cli._pending_playlist_run()))
    check("playlist recovery: interrupted run resumes full ordered list",
          len(_resume_calls) == 1
          and _resume_calls[0][0] == ["Artist - One", "Artist - Two"]
          and _resume_calls[0][3].get("track_numbers") == ["01", "02"]
          and _resume_calls[0][3].get("collection") == "Interrupted Mix")
    check("playlist recovery: successful resume marked complete",
          _cli._load_playlist_run().get("status") == "complete")
_sh0.rmtree(_failed_dir)

# unsupported playlist URLs fail immediately without launching Playwright
with _patch.object(_cli, "lucida_context") as _playlist_browser:
    with _ctxlib.redirect_stdout(_io.StringIO()):
        _unsupported_ok = _aio.run(_cli._playlist(
            "https://example.com/list", True, "qobuz", None, "original",
            tempfile.gettempdir(), False, 3))
check("playlist: unsupported links fail before opening a browser",
      not _unsupported_ok and not _playlist_browser.called)

_remote_list = _os.path.join(tempfile.gettempdir(), "lucidadl_remote_playlist.txt")
with _patch.object(_cli.api, "public_playlist_tracklist", _AsyncMock(return_value=(
        "Public Mix", [{"artist": "Artist", "title": "Song"}]))), \
     _patch.object(_cli, "PLAYLIST_TEXT_PATH", _remote_list), \
     _patch.object(_cli, "lucida_context") as _remote_browser:
    with _ctxlib.redirect_stdout(_io.StringIO()):
        _remote_ok = _aio.run(_cli._playlist(
            "https://open.spotify.com/playlist/abc", True, "qobuz", None,
            "original", tempfile.gettempdir(), False, 3))
check("playlist: Spotify dry-run does not launch a browser",
      _remote_ok and not _remote_browser.called and _os.path.exists(_remote_list))
try:
    _os.remove(_remote_list)
except OSError:
    pass

class _FakeBrowserContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *_args):
        return False


_youtube_list = _os.path.join(tempfile.gettempdir(), "lucidadl_youtube_playlist.txt")
with _patch.object(_cli, "PLAYLIST_TEXT_PATH", _youtube_list), \
     _patch.object(_cli, "lucida_context", return_value=_FakeBrowserContext()) as _yt_ctx, \
     _patch.object(_cli, "get_page", _AsyncMock(return_value=object())), \
     _patch.object(
         _cli.api, "browser_playlist_tracklist",
         _AsyncMock(return_value=(
             "YouTube Mix", [{"artist": "Artist", "title": "Song"}]
         )),
     ) as _yt_reader:
    with _ctxlib.redirect_stdout(_io.StringIO()):
        _youtube_ok = _aio.run(_cli._playlist(
            "https://music.youtube.com/playlist?list=PL123", True, "qobuz", None,
            "original", tempfile.gettempdir(), False, 3))
check("playlist: YouTube uses the complete browser reader",
      _youtube_ok and _yt_ctx.called and _yt_reader.await_count == 1)
try:
    _os.remove(_youtube_list)
except OSError:
    pass


_long_list = _os.path.join(tempfile.gettempdir(), "lucidadl_long_spotify.txt")
with _patch.object(
        _cli.api, "public_playlist_tracklist",
        _AsyncMock(side_effect=_cli.api.SpotifyPlaylistWindow("Long Mix", 150))), \
     _patch.object(_cli, "PLAYLIST_TEXT_PATH", _long_list), \
     _patch.object(_cli, "lucida_context", return_value=_FakeBrowserContext()) as _long_ctx, \
     _patch.object(_cli, "get_page", _AsyncMock(return_value=object())), \
     _patch.object(
         _cli.api, "spotify_browser_tracklist",
         _AsyncMock(return_value=(
             "Long Mix", [{"artist": "Artist", "title": "Song"}] * 150
         )),
     ) as _long_reader:
    with _ctxlib.redirect_stdout(_io.StringIO()):
        _long_ok = _aio.run(_cli._playlist(
            "https://open.spotify.com/playlist/long", True, "qobuz", None,
            "original", tempfile.gettempdir(), False, 3))
check("playlist: long Spotify list switches to the browser reader",
      _long_ok and _long_ctx.called and _long_reader.await_count == 1)
try:
    _os.remove(_long_list)
except OSError:
    pass

_tidal_list = _os.path.join(tempfile.gettempdir(), "lucidadl_long_tidal.txt")
with _patch.object(
        _cli.api, "public_playlist_tracklist",
        _AsyncMock(side_effect=_cli.api.TidalPlaylistWindow("Long TIDAL Mix"))), \
     _patch.object(_cli, "PLAYLIST_TEXT_PATH", _tidal_list), \
     _patch.object(_cli, "lucida_context", return_value=_FakeBrowserContext()) as _tidal_ctx, \
     _patch.object(_cli, "get_page", _AsyncMock(return_value=object())), \
     _patch.object(
         _cli.api, "tidal_browser_tracklist",
         _AsyncMock(return_value=(
             "Long TIDAL Mix", [{"artist": "Artist", "title": "Song"}] * 75
         )),
     ) as _tidal_reader:
    with _ctxlib.redirect_stdout(_io.StringIO()):
        _tidal_ok = _aio.run(_cli._playlist(
            "https://tidal.com/playlist/long", True, "qobuz", None,
            "original", tempfile.gettempdir(), False, 3))
check("playlist: long TIDAL list switches to the full browser session",
      _tidal_ok and _tidal_ctx.called and _tidal_reader.await_count == 1)
try:
    _os.remove(_tidal_list)
except OSError:
    pass

check("playlist: failures before download retain recovery context",
      _cli._failed_result(
          ["Artist - One", "Artist - Two"], "track", "My Mix", ["01", "02"]
      )[1] == [
          FailedItem("track", "Artist - One", "My Mix", "01"),
          FailedItem("track", "Artist - Two", "My Mix", "02"),
      ])

# command contracts used by scripts: missing input/search failure must be non-zero,
# while an explicit search cancellation remains a normal successful exit
_runner = _CliRunner()
_missing_batch = _runner.invoke(
    _cli.cli, ["tracks", "--file", _os.path.join(tempfile.gettempdir(),
                                                  "lucidadl-no-such-batch.txt")])
check("batch: missing file returns exit 1 with guidance",
      _missing_batch.exit_code == 1 and "Batch file not found" in _missing_batch.output
      and "--file" in _missing_batch.output)

_search_failure = ({"ok": 0, "skip": 0, "fail": 1}, [])
with _patch.object(_cli, "_search", _AsyncMock(return_value=_search_failure)):
    _search_failed = _runner.invoke(_cli.cli, ["search", "anything"])
check("search: failure result returns exit 1", _search_failed.exit_code == 1)
with _patch.object(_cli, "_search", _AsyncMock(return_value=None)):
    _search_cancelled = _runner.invoke(_cli.cli, ["search", "anything"])
check("search: explicit cancellation returns exit 0", _search_cancelled.exit_code == 0)

_help = _runner.invoke(_cli.cli, ["--help"])
check("cli: developer debug command is hidden", "  debug " not in _help.output)
_version = _runner.invoke(_cli.cli, ["--version"])
check("cli: source version matches release metadata",
      _version.exit_code == 0 and "1.4.3" in _version.output)  # x-release-please-version

# --- Lidarr / Soularr-style integration ---
import json as _json
import os as _os2
import tempfile as _tmp2
import httpx as _httpx
from lucidadl import lidarr as _ld

check("lidarr: album query", _ld.album_query(
    {"title": "Discovery", "artist": {"artistName": "Daft Punk"}}) == "Daft Punk - Discovery")
check("lidarr: album query needs artist", _ld.album_query({"title": "X"}) == "")
check("lidarr: map_path identity", _ld.map_path("/a/b", "/a", None) == "/a/b")
check("lidarr: map_path remaps", _ld.map_path("/dl/x/y", "/dl", "/data/dl") == "/data/dl/x/y")
check("lidarr: map_path root", _ld.map_path("/dl", "/dl", "/data/dl") == "/data/dl")
with _tmp2.TemporaryDirectory() as _d:
    _st = _ld.AttemptState(_os2.path.join(_d, "s.json"))
    check("lidarr: new album is tried", _st.should_try(1, 24))
    _st.record(1, "q", "no-download", now=1000.0)
    check("lidarr: cooldown blocks", not _st.should_try(1, 24, now=1000.0 + 3600))
    check("lidarr: cooldown expires", _st.should_try(1, 24, now=1000.0 + 25 * 3600))
    check("lidarr: state persists",
          not _ld.AttemptState(_os2.path.join(_d, "s.json")).should_try(
              1, 24, now=1000.0 + 3600))
    _stage = _os2.path.join(_d, "stage", "Artists", "A", "Alb")
    _os2.makedirs(_stage)
    open(_os2.path.join(_stage, "01.flac"), "w").close()
    check("lidarr: audio_dirs finds album", _ld.audio_dirs(_os2.path.join(_d, "stage")) == [_stage])
    _ld.prune_empty(_os2.path.join(_d, "stage"))
    check("lidarr: prune keeps audio", _os2.path.isdir(_stage))
    _os2.remove(_os2.path.join(_stage, "01.flac"))
    _ld.prune_empty(_os2.path.join(_d, "stage"))
    check("lidarr: prune removes empty tree", not _os2.path.exists(_os2.path.join(_d, "stage")))
    # consolidate: nested files (+ art, + a name clash) end up in one release-named folder
    _st3 = _os2.path.join(_d, "st3")
    for _sub in ("Artists/A/B", "Artists/A/C"):
        _os2.makedirs(_os2.path.join(_st3, _sub))
    open(_os2.path.join(_st3, "Artists/A/B/01.flac"), "w").close()
    open(_os2.path.join(_st3, "Artists/A/B/cover.jpg"), "w").close()
    open(_os2.path.join(_st3, "Artists/A/C/01.flac"), "w").close()
    _tgt = _ld.consolidate(_st3, "A - Alb")
    check("lidarr: consolidate gathers files into 'Artist - Album'",
          _os2.path.basename(_tgt) == "A - Alb"
          and sorted(_os2.listdir(_tgt)) == ["01 (1).flac", "01.flac", "cover.jpg"]
          and not _os2.path.exists(_os2.path.join(_st3, "Artists")))
    check("lidarr: consolidate is idempotent", _ld.consolidate(_st3, "A - Alb") == _tgt
          and len(_os2.listdir(_tgt)) == 3)
    for _f in ("01.flac", "01 (1).flac"):
        _os2.remove(_os2.path.join(_tgt, _f))
    _ld.prune_empty(_st3)
    check("lidarr: prune clears leftover art once audio is gone", not _os2.path.exists(_st3))


def _fake_lidarr(request):
    if request.url.path.endswith("/wanted/missing"):
        page = int(request.url.params["page"])
        rec = [{"id": page, "title": f"T{page}", "artist": {"artistName": "A"}}]
        return _httpx.Response(200, json={"records": rec, "totalRecords": 2})
    if request.url.path.endswith("/command") and request.method == "POST":
        body = _json.loads(request.content)
        assert body["name"] == "DownloadedAlbumsScan" and body["path"] == "/x"
        return _httpx.Response(201, json={"id": 7, "status": "queued"})
    if request.url.path.endswith("/command/7"):
        return _httpx.Response(200, json={"id": 7, "status": "completed"})
    return _httpx.Response(404)


async def _lidarr_flow():
    c = _ld.LidarrClient("http://lidarr", "key")
    c.http._transport = _httpx.MockTransport(_fake_lidarr)
    try:
        albums = await c.wanted()
        status = await c.import_folder("/x", poll=0.01)
        return len(albums), status
    finally:
        await c.aclose()


check("lidarr: paged wanted + import scan", _aio.run(_lidarr_flow()) == (2, "completed"))

# Soularr-style config.ini
import logging as _lg
with _tmp2.TemporaryDirectory() as _d:
    _cfgp = _os2.path.join(_d, "config.ini")
    open(_cfgp, "w").write(
        "[Lidarr]\napi_key = k\nhost_url = http://l:8686\ndownload_dir = /remote\n"
        "disable_sync = True\n[Lucida]\nservice = amazon\njobs = 5\n"
        "[Search Settings]\nsearch_source = cutoff_unmet\nsearch_type = first_page\n"
        "number_of_albums_to_grab = 4\ntitle_blacklist = Live,Remix\n"
        "remove_wanted_on_failure = True\n"
        "[Logging]\nformat = %(message)s\n")
    _s = _ld.resolve(_ld.load_config(_cfgp), {})
    check("config: sections map to settings",
          (_s.url, _s.api_key, _s.remote_dir, _s.service, _s.jobs, _s.limit) ==
          ("http://l:8686", "k", "/remote", "amazon", 5, 4))
    check("config: flags and enums", _s.disable_sync and _s.cutoff and _s.remove_on_failure
          and _s.search_type == "first_page")
    check("config: literal % in log format kept", _s.log_format == "%(message)s")
    check("config: blacklist lowercased", _s.blacklist == ["live", "remix"])
    _o = _ld.resolve(_ld.load_config(_cfgp), {"service": "qobuz", "limit": 9, "hidden": True})
    check("config: CLI override beats file",
          (_o.service, _o.limit, _o.hidden, _o.jobs) == ("qobuz", 9, True, 5))
    _dflt = _ld.resolve(_ld.load_config(None), {})
    check("config: defaults match Soularr style",
          (_dflt.search_type, _dflt.limit, _dflt.retry_after, _dflt.log_level) ==
          ("incrementing_page", 10, 24.0, "INFO"))
    try:
        _ld.resolve(_ld.load_config(None), {"search_type": "bogus"})
        _bad = False
    except _ld.LidarrError:
        _bad = True
    check("config: invalid search_type rejected", _bad)
    check("config: find_config explicit", _ld.find_config(_cfgp) == _cfgp)
    check("blacklist matches title", _ld.blacklisted({"title": "Live at X"}, ["live"])
          and not _ld.blacklisted({"title": "Studio"}, ["live"]))
    _st2 = _ld.AttemptState(_os2.path.join(_d, "p.json"))
    check("incrementing page starts at 1 and wraps",
          _st2.next_page(3) == 1 and (_st2.set_page(3) or _st2.next_page(3)) == 3
          and (_st2.set_page(9) or _st2.next_page(3)) == 1)

# --- lucidarr cycle behaviour (mocked Lidarr + downloader) ---
import logging as _lg2
from types import SimpleNamespace as _NS
from unittest.mock import patch as _p2

_RealState = _ld.AttemptState

class _FakeLidarr:
    instances = []
    def __init__(self, url, key):
        self.unmonitored, self.imports = [], []
        _FakeLidarr.instances.append(self)
    async def check(self): return "3.1"
    async def wanted_page(self, cutoff, page, size):
        return {"records": _FakeLidarr.albums, "totalRecords": len(_FakeLidarr.albums)}
    async def wanted(self, cutoff=False): return _FakeLidarr.albums
    async def import_folder(self, path, wait=300): 
        self.imports.append(path)
        for f in _FakeLidarr.import_effect: f(path)
        return "completed"
    async def manual_import(self, path, artist_id, album_id, wait=300, poll=3, replace=False):
        status = await self.import_folder(path, wait)
        return status, 1, 1, []
    async def unmonitor(self, aid): self.unmonitored.append(aid)
    async def aclose(self): pass

def _cycle(albums, run_results, **over):
    """Run one cycle; run_results = list of (ok, fail) per _run call, 'files' decides audio."""
    with _tmp2.TemporaryDirectory() as d:
        cfg = _ld.resolve(_ld.load_config(None), {"limit": 10, "search_type": "first_page",
                                                  "retry_after": 24, **over})
        cfg.download_dir = d
        _FakeLidarr.albums = albums
        _FakeLidarr.import_effect = [lambda path: [_os2.remove(_os2.path.join(r, f))
                                      for r, _, fs in _os2.walk(path) for f in fs]]
        calls = []
        async def fake_run(items, kind, svc, cc, ds, out, *a, **k):
            ok, fail = run_results[len(calls)] if len(calls) < len(run_results) else (0, 1)
            calls.append(items[0])
            if ok:
                _os2.makedirs(out + "/Artists/A/B", exist_ok=True)
                open(out + "/Artists/A/B/01.flac", "w").close()
            return {"ok": ok, "skip": 0, "fail": fail}, []
        _FakeLidarr.instances.clear()
        with _p2.object(_ld, "LidarrClient", _FakeLidarr), \
             _p2.object(_cli, "_run", fake_run), \
             _p2.object(_cli, "load_clearance", lambda: (None, "ua")), \
             _p2.object(_ld, "AttemptState", lambda: _RealState(d + "/st.json")), \
             _p2.object(_ld, "FAILURE_LIST_PATH", d + "/fail.txt"):
            stats = _aio.run(_cli._lucidarr_cycle(cfg))
            st = _RealState(d + "/st.json")
        return stats, _FakeLidarr.instances[0], calls, st, d

_alb = lambda i: {"id": i, "title": f"T{i}", "artist": {"artistName": "A"}}
_stats, _fl, _calls, _st, _ = _cycle([_alb(1), _alb(2)], [(3, 0), (3, 0)])
check("cycle: downloads then imports each album", _stats["imported"] == 2 and len(_fl.imports) == 2)
check("cycle: Lidarr scans one folder named like the release ('Artist - Album')",
      [_os2.path.basename(p) for p in _fl.imports] == ["A - T1", "A - T2"])
_stats, _fl, _calls, _st, _ = _cycle([_alb(i) for i in range(1, 6)], [], remove_on_failure=True)
check("cycle: outage aborts after 3 failures, records nothing, unmonitors nothing",
      len(_calls) == 3 and not _st.data and not _fl.unmonitored)
_stats, _fl, _calls, _st, _ = _cycle([_alb(1), _alb(2)], [(0, 1), (3, 0)], remove_on_failure=True)
check("cycle: failure before a success is settled and unmonitored once lucida proves OK",
      _fl.unmonitored == [1] and "1" in _st.data and _stats["imported"] == 1)
_stats, _fl, _calls, _st, _ = _cycle([_alb(1)], [(2, 1)])
check("cycle: partial album is not imported", not _fl.imports and _st.data["1"]["result"] == "partial")
# an interrupted earlier download (audio staged, no completion marker) is discarded, then fetched fresh
def _cycle_pre(prefill_complete):
    with _tmp2.TemporaryDirectory() as d:
        cfg = _ld.resolve(_ld.load_config(None), {"limit": 10, "search_type": "first_page",
                                                  "retry_after": 24})
        cfg.download_dir = d
        _FakeLidarr.albums = [_alb(1)]
        _FakeLidarr.import_effect = [lambda path: [_os2.remove(_os2.path.join(r, f))
                                      for r, _, fs in _os2.walk(path) for f in fs]]
        stage = _ld.staging_dir(d, _alb(1))
        _os2.makedirs(stage + "/Artists/A/B")
        open(stage + "/Artists/A/B/old.flac", "w").close()
        if prefill_complete:
            _ld.mark_complete(stage)
        calls = []
        async def fake_run(items, kind, svc, cc, ds, out, *a, **k):
            calls.append(1)
            _os2.makedirs(out + "/Artists/A/B", exist_ok=True)
            open(out + "/Artists/A/B/new.flac", "w").close()
            return {"ok": 1, "skip": 0, "fail": 0}, []
        _FakeLidarr.instances.clear()
        with _p2.object(_ld, "LidarrClient", _FakeLidarr), _p2.object(_cli, "_run", fake_run), \
             _p2.object(_cli, "load_clearance", lambda: (None, "ua")), \
             _p2.object(_ld, "AttemptState", lambda: _RealState(d + "/st.json")):
            _aio.run(_cli._lucidarr_cycle(cfg))
        return len(calls), len(_FakeLidarr.instances[0].imports)
check("cycle: incomplete staged download is discarded and re-downloaded", _cycle_pre(False) == (1, 1))
check("cycle: complete staged download is re-scanned without downloading", _cycle_pre(True) == (0, 1))
_stats, _fl, _calls, _st, _ = _cycle([_alb(1)], [(3, 0)], disable_sync=True)
check("cycle: disable_sync records 'staged', no import",
      not _fl.imports and _st.data["1"]["result"] == "staged")

class _Boom(_FakeLidarr):
    async def import_folder(self, path, wait=300):
        raise _ld.LidarrError("down")
    async def manual_import(self, *a, **k):
        raise _ld.LidarrError("down")
with _p2.object(_ld, "LidarrClient", _Boom), _tmp2.TemporaryDirectory() as _d3:
    _FakeLidarr.albums = [_alb(1), _alb(2)]
    _cfg = _ld.resolve(_ld.load_config(None), {"search_type": "first_page", "retry_after": 24})
    _cfg.download_dir = _d3
    _n = []
    async def _fr(items, kind, svc, cc, ds, out, *a, **k):
        _n.append(1); _os2.makedirs(out + "/x", exist_ok=True)
        open(out + "/x/1.flac", "w").close()
        return {"ok": 1, "skip": 0, "fail": 0}, []
    with _p2.object(_cli, "_run", _fr), _p2.object(_cli, "load_clearance", lambda: (None, "u")), \
         _p2.object(_ld, "AttemptState", lambda: _RealState(_d3 + "/s.json")):
        _bs = _aio.run(_cli._lucidarr_cycle(_cfg))
    check("cycle: Lidarr import error is recorded and stops the cycle",
          len(_n) == 1 and _bs["failed"] == 1
          and _RealState(_d3 + "/s.json").data["1"]["result"] == "import-error")
for _bad in ({"limit": 0}, {"jobs": 0}):
    try:
        _ld.resolve(_ld.load_config(None), _bad); _ok = False
    except _ld.LidarrError:
        _ok = True
    check(f"config: rejects {_bad}", _ok)
check("find_config: missing explicit path is not silently replaced",
      _ld.find_config("/definitely/not/here.ini") is None)

# --- clearance web page ---
import threading as _th
from lucidadl import webui as _web, session as _sess

check("web: pasted JSON parsed", _web.parse_submission('{"cf_clearance":"abc","ua":"UA/1"}')
      == ("abc", "UA/1"))
check("web: cookie may be absent", _web.parse_submission("", "", "UA/1") == (None, "UA/1"))
_rej = []
for _args in (("not json",), ('{"cf_clearance":"a"}',), ("", "bad\r\nX: 1", "UA"),
              ("", "ok", "UA\nInjected: 1"), ("[1]",)):
    try:
        _web.parse_submission(*_args); _rej.append(False)
    except _web.BadSubmission:
        _rej.append(True)
check("web: bad / injecting submissions rejected", all(_rej))
try:
    _web.make_server("127.0.0.1", 0, ""); _nopw = False
except ValueError:
    _nopw = True
check("web: refuses to start without a password", _nopw)

with _tmp2.TemporaryDirectory() as _wd, _p2.object(
        _sess, "CLEARANCE_PATH", _os2.path.join(_wd, "clearance.json")), \
        _p2.object(_web.time, "sleep", lambda s: None):
    _srv = _web.make_server("127.0.0.1", 0, "s3cret")
    _port = _srv.server_address[1]
    _th.Thread(target=_srv.serve_forever, daemon=True).start()
    _u = f"http://127.0.0.1:{_port}"
    try:
        check("web: page loads", _httpx.get(_u + "/").status_code == 200)
        _lg = _httpx.get(_u + "/logo.svg")
        check("web: logo served as SVG", _lg.status_code == 200
              and _lg.headers["content-type"] == "image/svg+xml" and b"<svg" in _lg.content
              and b"<script" not in _lg.content)
        check("web: wrong password refused, nothing saved",
              _httpx.post(_u + "/upload", data={"password": "no", "pasted":
                          '{"cf_clearance":"x","ua":"U"}'}).status_code == 403
              and not _os2.path.exists(_sess.CLEARANCE_PATH))
        _r = _httpx.post(_u + "/upload", data={"password": "s3cret", "pasted":
                         '{"cf_clearance":"cookie1","ua":"UA/9"}'})
        check("web: form upload saved", _r.status_code == 200
              and _sess.load_clearance() == ("cookie1", "UA/9"))
        check("web: page never reveals the cookie", "cookie1" not in _httpx.get(_u + "/").text)
        check("web: api rejects missing/incorrect bearer",
              _httpx.post(_u + "/api/clearance", json={"ua": "U"}).status_code == 403)
        _r = _httpx.post(_u + "/api/clearance", json={"cf_clearance": "c2", "ua": "UA/10"},
                         headers={"Authorization": "Bearer s3cret"})
        check("web: api upload saved", _r.status_code == 200
              and _sess.load_clearance() == ("c2", "UA/10"))
        check("web: oversized body rejected", _httpx.post(
              _u + "/api/clearance", content=b"x" * 20000,
              headers={"Authorization": "Bearer s3cret"}).status_code == 400)
    finally:
        _srv.shutdown()
check("cli: web + push-clearance registered",
      "web" in _cli.cli.commands and "push-clearance" in _cli.cli.commands)

# --- Manual Import API ---
_posted = []
def _fake_manual(request):
    if request.url.path.endswith("/manualimport"):
        q = dict(request.url.params)
        assert q["folder"] == "/r/A - T" and q["artistId"] == "5" and q["replaceExistingFiles"] == "false"
        return _httpx.Response(200, json=[
            {"name": "01", "path": "/r/A - T/01.flac", "artist": {"id": 5}, "album": {"id": 9},
             "albumReleaseId": 77, "tracks": [{"id": 101}], "quality": {"q": 1}, "rejections": []},
            {"name": "02", "path": "/r/A - T/02.flac", "artist": {"id": 5}, "album": {"id": 9},
             "albumReleaseId": 77, "tracks": [{"id": 102}], "quality": {"q": 1},
             "rejections": [{"reason": "Not an upgrade"}]},
            {"name": "03", "path": "/r/A - T/03.flac", "artist": {}, "album": {}, "tracks": [],
             "rejections": [{"reason": "Unknown Artist"}]},
            {"name": "04", "path": "/r/A - T/04.flac", "artist": {"id": 5}, "album": {"id": 10},
             "albumReleaseId": 1, "tracks": [{"id": 1}], "rejections": []}])
    if request.url.path.endswith("/command") and request.method == "POST":
        _posted.append(_json.loads(request.content))
        return _httpx.Response(201, json={"id": 3, "status": "queued"})
    if request.url.path.endswith("/command/3"):
        return _httpx.Response(200, json={"status": "completed"})
    return _httpx.Response(404)

async def _manual_flow(items_empty=False):
    c = _ld.LidarrClient("http://lidarr", "key")
    c.http._transport = _httpx.MockTransport(
        (lambda r: _httpx.Response(200, json=[]) if r.url.path.endswith("/manualimport")
         else _fake_manual(r)) if items_empty else _fake_manual)
    try:
        return await c.manual_import("/r/A - T", 5, 9, poll=0.01)
    finally:
        await c.aclose()

_mi = _aio.run(_manual_flow())
check("release folder name follows Soularr's 'Artist - Title (Year)'",
      _ld.release_folder_name({"title": "Disco/very", "artist": {"artistName": "Daft Punk"},
                               "releaseDate": "2001-03-12T00:00:00Z"}) == "Daft Punk - Disco_very (2001)"
      and _ld.release_folder_name(_alb(1)) == "A - T1")
with _tmp2.TemporaryDirectory() as _td:
    from mutagen.easyid3 import EasyID3 as _E3
    _mp3 = _os2.path.join(_td, "01.mp3"); open(_mp3, "wb").close()
    _bad = _os2.path.join(_td, "02.flac"); open(_bad, "wb").close()   # not real audio
    check("tag_files: sets albumartist/album, skips unreadable files",
          _ld.tag_files(_td, "Tom Cardy", "Dancefloor") == 1
          and _E3(_mp3)["albumartist"] == ["Tom Cardy"] and _E3(_mp3)["album"] == ["Dancefloor"])
check("manual import: imports only files matched to the wanted album",
      _mi[0] == "completed" and _mi[1] == 2 and _mi[2] == 4)
check("manual import: payload carries ids, quality and move mode",
      _posted[-1]["name"] == "ManualImport" and _posted[-1]["importMode"] == "move"
      and [f["trackIds"] for f in _posted[-1]["files"]] == [[101], [102]]
      and _posted[-1]["files"][0]["albumReleaseId"] == 77
      and _posted[-1]["files"][0]["artistId"] == 5 and _posted[-1]["files"][0]["albumId"] == 9)
check("manual import: rejection reasons are surfaced",
      any("Unknown Artist" in r for r in _mi[3]) and any("Not an upgrade" in r for r in _mi[3])
      and any("matched album id 10" in r for r in _mi[3]))
_before = len(_posted)
_mi2 = _aio.run(_manual_flow(items_empty=True))
check("manual import: nothing matched -> 'unmatched', no command posted",
      _mi2[0] == "unmatched" and len(_posted) == _before)
check("config: import_method defaults to auto",
      _ld.resolve(_ld.load_config(None), {}).import_method == "auto")
try:
    _ld.resolve(_ld.load_config(None), {"import_method": "nope"}); _imok = False
except _ld.LidarrError:
    _imok = True
check("config: invalid import_method rejected", _imok)
check("cli: lucidarr command + soularr alias registered",
      "lucidarr" in _cli.cli.commands and "soularr" in _cli.cli.commands)

print()
if fails:
    print(f"{len(fails)} FAILURE(S): {fails}")
    raise SystemExit(1)
print("ALL OFFLINE TESTS PASSED")
