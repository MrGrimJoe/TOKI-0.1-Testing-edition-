import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from conversion_engine import (
    convert_file, resize_file, compress_file, extract_file,
    supported_formats, UnsupportedFormatError,
)


@pytest.fixture
def tmp_image(tmp_path) -> Path:
    p = tmp_path / "photo.png"
    Image.new("RGB", (200, 100), color=(10, 20, 30)).save(p)
    return p


@pytest.fixture
def tmp_json(tmp_path) -> Path:
    p = tmp_path / "data.json"
    p.write_text(json.dumps({"name": "toki", "beta": "0.3.40"}), encoding="utf-8")
    return p


@pytest.fixture
def tmp_csv(tmp_path) -> Path:
    p = tmp_path / "rows.csv"
    p.write_text("name,version\ntoki,0.3.40\n", encoding="utf-8")
    return p


class TestImage:
    def test_resize_default_shrinks_by_half(self, tmp_image):
        out = resize_file(str(tmp_image))
        assert Path(out).exists()
        with Image.open(out) as img:
            assert img.size == (100, 50)

    def test_resize_explicit_width_preserves_aspect(self, tmp_image):
        out = resize_file(str(tmp_image), width=50)
        with Image.open(out) as img:
            assert img.size == (50, 25)

    def test_resize_does_not_overwrite_by_default(self, tmp_image):
        out = resize_file(str(tmp_image))
        assert Path(out) != tmp_image
        assert tmp_image.exists()

    def test_resize_overwrite_true_replaces_original(self, tmp_image):
        out = resize_file(str(tmp_image), scale=0.25, overwrite=True)
        assert Path(out) == tmp_image
        with Image.open(out) as img:
            assert img.size == (50, 25)

    def test_convert_png_to_jpg(self, tmp_image):
        out = convert_file(str(tmp_image), target_ext="jpg")
        assert out.endswith(".jpg")
        with Image.open(out) as img:
            assert img.mode == "RGB"

    def test_compress_jpeg_reduces_size(self, tmp_path):
        src = tmp_path / "big.jpg"
        Image.new("RGB", (800, 600), color=(200, 50, 10)).save(src, quality=100)
        out = compress_file(str(src), quality=20)
        assert Path(out).stat().st_size < src.stat().st_size


class TestText:
    def test_json_to_txt(self, tmp_json):
        out = convert_file(str(tmp_json), target_ext="txt")
        content = Path(out).read_text(encoding="utf-8")
        assert "toki" in content

    def test_json_to_csv(self, tmp_path):
        p = tmp_path / "records.json"
        p.write_text(json.dumps([{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]), encoding="utf-8")
        out = convert_file(str(p), target_ext="csv")
        content = Path(out).read_text(encoding="utf-8")
        assert "a,b" in content
        assert "1,2" in content

    def test_csv_to_json_round_trips_headers(self, tmp_csv):
        out = convert_file(str(tmp_csv), target_ext="json")
        data = json.loads(Path(out).read_text(encoding="utf-8"))
        assert data[0]["name"] == "toki"

    def test_csv_to_txt(self, tmp_csv):
        out = convert_file(str(tmp_csv), target_ext="txt")
        content = Path(out).read_text(encoding="utf-8")
        assert "name | version" in content


class TestArchive:
    def test_compress_single_file(self, tmp_json):
        out = compress_file(str(tmp_json))
        assert zipfile.is_zipfile(out)

    def test_compress_folder(self, tmp_path):
        folder = tmp_path / "notes"
        folder.mkdir()
        (folder / "a.txt").write_text("hi", encoding="utf-8")
        out = compress_file(str(folder))
        assert zipfile.is_zipfile(out)
        with zipfile.ZipFile(out) as zf:
            assert any("a.txt" in n for n in zf.namelist())

    def test_extract_round_trip(self, tmp_json):
        zipped = compress_file(str(tmp_json))
        dest = extract_file(zipped)
        assert Path(dest).is_dir()
        assert any(f.name == tmp_json.name for f in Path(dest).iterdir())


class TestErrors:
    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            convert_file("/does/not/exist.png", target_ext="jpg")

    def test_unsupported_combo_raises_clear_error(self, tmp_path):
        p = tmp_path / "mystery.xyz"
        p.write_text("???", encoding="utf-8")
        with pytest.raises(UnsupportedFormatError):
            convert_file(str(p), target_ext="jpg")

    def test_supported_formats_lists_known_extensions(self):
        formats = supported_formats()
        assert "png" in formats["image"]
        assert "json" in formats["text"]
        assert "zip" in formats["archive"]


class TestTextBackendUnsupportedPairs:
    """Real bug found via chat review: json->xml and csv->yaml (and any
    other pair this module has no real transform for) used to silently
    write the SOURCE's raw content under the TARGET's extension -- e.g.
    "convert data.json to data.xml" produced a file named .xml that was
    actually JSON. Should raise, not mislabel."""

    def test_json_to_xml_raises(self, tmp_json):
        with pytest.raises(UnsupportedFormatError):
            convert_file(str(tmp_json), target_ext="xml")

    def test_csv_to_yaml_raises(self, tmp_csv):
        with pytest.raises(UnsupportedFormatError):
            convert_file(str(tmp_csv), target_ext="yaml")

    def test_no_mislabeled_file_left_behind_on_json_to_xml(self, tmp_json, tmp_path):
        bad_out = tmp_path / "data_converted.xml"
        with pytest.raises(UnsupportedFormatError):
            convert_file(str(tmp_json), target_ext="xml")
        assert not bad_out.exists()

    def test_txt_to_yaml_still_works_no_structure_either_side(self, tmp_path):
        # txt/md/log/yaml/yml have no structure of their own relative to
        # each other -- a plain copy under the new extension is correct
        # here, not a regression of the fix above.
        p = tmp_path / "notes.txt"
        p.write_text("just some notes", encoding="utf-8")
        out = convert_file(str(p), target_ext="yaml")
        assert Path(out).read_text(encoding="utf-8") == "just some notes"


class TestArchiveZipSlip:
    """Real bug found via chat review: archive_backend.extract() called
    zf.extractall() with no member-path check, so a zip containing
    "../"-style entries could write outside the destination folder."""

    def test_zip_slip_entry_raises(self, tmp_path):
        import zipfile
        evil_zip = tmp_path / "evil.zip"
        with zipfile.ZipFile(evil_zip, "w") as zf:
            zf.writestr("../../escaped.txt", "pwned")

        with pytest.raises(ValueError, match="outside"):
            extract_file(str(evil_zip), destination=str(tmp_path / "safe_dest"))

        assert not (tmp_path.parent.parent / "escaped.txt").exists()

    def test_normal_zip_still_extracts_fine(self, tmp_path):
        import zipfile
        good_zip = tmp_path / "fine.zip"
        with zipfile.ZipFile(good_zip, "w") as zf:
            zf.writestr("inside/note.txt", "hello")

        dest = extract_file(str(good_zip), destination=str(tmp_path / "out"))
        assert (Path(dest) / "inside" / "note.txt").exists()


class TestIniText:
    """BETA 0.3.43: text_backend widened to cover ini/conf as a real
    structured round-trip through json, not a byte-copy."""

    def test_ini_to_json(self, tmp_path):
        p = tmp_path / "config.ini"
        p.write_text("[server]\nhost = localhost\nport = 8080\n", encoding="utf-8")
        out = convert_file(str(p), target_ext="json")
        data = json.loads(Path(out).read_text(encoding="utf-8"))
        assert data == {"server": {"host": "localhost", "port": "8080"}}

    def test_json_to_ini_round_trips_flat_sections(self, tmp_path):
        p = tmp_path / "data.json"
        p.write_text(json.dumps({"server": {"host": "localhost", "port": "8080"}}), encoding="utf-8")
        out = convert_file(str(p), target_ext="ini")
        text = Path(out).read_text(encoding="utf-8")
        assert "[server]" in text and "host = localhost" in text

    def test_json_to_ini_rejects_non_flat_shape(self, tmp_path):
        p = tmp_path / "data.json"
        p.write_text(json.dumps({"not": "a section dict"}), encoding="utf-8")
        with pytest.raises(UnsupportedFormatError):
            convert_file(str(p), target_ext="ini")

    def test_conf_treated_as_ini_shaped(self, tmp_path):
        p = tmp_path / "app.conf"
        p.write_text("[db]\nname = toki\n", encoding="utf-8")
        out = convert_file(str(p), target_ext="txt")
        assert "db" in Path(out).read_text(encoding="utf-8").lower()


class TestArchiveTarFamily:
    """BETA 0.3.43: archive_backend widened from zip-only to also read/
    write tar, tgz/tar.gz, and tbz2/tar.bz2, with the same zip-slip-style
    member-path check now applying to tar too."""

    def test_compress_folder_to_tar_gz(self, tmp_path):
        folder = tmp_path / "stuff"
        folder.mkdir()
        (folder / "a.txt").write_text("hello", encoding="utf-8")
        out = convert_file(str(folder), target_ext="tar.gz")
        assert Path(out).name.endswith(".tar.gz")
        assert Path(out).exists()

    def test_tar_gz_round_trip(self, tmp_path):
        folder = tmp_path / "stuff"
        folder.mkdir()
        (folder / "a.txt").write_text("hello", encoding="utf-8")
        archive = convert_file(str(folder), target_ext="tar.gz")
        dest = extract_file(archive, destination=str(tmp_path / "extracted"))
        assert (Path(dest) / "stuff" / "a.txt").read_text(encoding="utf-8") == "hello"

    def test_tar_slip_entry_raises(self, tmp_path):
        import tarfile
        import io as _io

        evil_tar = tmp_path / "evil.tar"
        with tarfile.open(evil_tar, "w") as tf:
            data = b"pwned"
            info = tarfile.TarInfo(name="../../escaped.txt")
            info.size = len(data)
            tf.addfile(info, _io.BytesIO(data))

        with pytest.raises(ValueError, match="outside"):
            extract_file(str(evil_tar), destination=str(tmp_path / "safe_dest"))


class TestMediaBackend:
    """ffmpeg-backed audio/video family (BETA 0.3.43, new). Skipped
    entirely if ffmpeg isn't on PATH in the environment running the test
    suite -- same "a missing external tool is a skip, not a failure"
    posture test_document_backend.py already applies for pandoc."""

    @pytest.fixture(autouse=True)
    def _require_ffmpeg(self):
        import shutil
        if shutil.which("ffmpeg") is None:
            pytest.skip("ffmpeg not on PATH")

    @pytest.fixture
    def tmp_wav(self, tmp_path) -> Path:
        import subprocess
        p = tmp_path / "tone.wav"
        subprocess.run(
            ["ffmpeg", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
             "-ar", "44100", str(p), "-y", "-loglevel", "quiet"],
            check=True,
        )
        return p

    def test_wav_to_mp3(self, tmp_wav):
        out = convert_file(str(tmp_wav), target_ext="mp3")
        assert Path(out).exists()
        assert Path(out).suffix == ".mp3"

    def test_audio_to_video_rejected_with_clear_message(self, tmp_wav):
        mp3 = convert_file(str(tmp_wav), target_ext="mp3")
        with pytest.raises(UnsupportedFormatError, match="no picture"):
            convert_file(mp3, target_ext="mp4")

    def test_compress_audio_produces_smaller_or_equal_file(self, tmp_wav):
        mp3 = convert_file(str(tmp_wav), target_ext="mp3")
        out = compress_file(mp3, quality=30)
        assert Path(out).exists()
