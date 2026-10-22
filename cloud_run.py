#!/usr/bin/env python3
"""Run a small, reviewable PDF pilot using a ZIP from this repository's Releases."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import urllib.parse
import urllib.request
import zipfile

import converter as c
from prepare_upload import prepare_copy

HERE = Path(__file__).resolve().parent
MAX_ARCHIVE = 2_000_000_000
MAX_EXPANDED = 6_000_000_000
MAX_FILES = 250
ALLOWED_OUTPUTS = {"PILOT PDFs", "WEBSITE PDFs", "REVIEW", "REPORTS"}


def extract_inputs(archive, destination):
    """Accept PDF files plus one optional manifest; reject unsafe ZIP entries."""
    destination = Path(destination)
    if not 0 < Path(archive).stat().st_size <= MAX_ARCHIVE:
        raise ValueError("Input archive exceeds size limit or is empty")
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("Input extraction folder must be empty")
    entries, names, pdfs, total = [], set(), 0, 0
    with zipfile.ZipFile(archive) as bundle:
        if len(bundle.infolist()) > MAX_FILES * 10:
            raise ValueError("Too many ZIP entries")
        for info in bundle.infolist():
            name = info.filename
            path = PurePosixPath(name)
            if (not name or "\\" in name or path.is_absolute() or
                    any(p in (".", "..") for p in name.split("/")) or
                    any(":" in p or p.endswith((" ", ".")) for p in path.parts) or
                    stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1):
                raise ValueError("Unsafe or encrypted ZIP entry")
            if info.is_dir():
                continue
            key = name.casefold()
            if key in names:
                raise ValueError("Duplicate or case-colliding ZIP filename")
            names.add(key)
            if path.suffix.casefold() != ".pdf" and name != "manifest.json":
                raise ValueError("Input ZIP may contain only PDFs and manifest.json")
            pdfs += path.suffix.casefold() == ".pdf"
            total += info.file_size
            if pdfs > MAX_FILES or total > MAX_EXPANDED:
                raise ValueError("Input ZIP exceeds file count or expanded size limit")
            entries.append(info)
        if not pdfs:
            raise ValueError("Input ZIP contains no PDFs")
        destination.mkdir(parents=True, exist_ok=True)
        for info in entries:
            target = destination.joinpath(*PurePosixPath(info.filename).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
    manifest = destination / "manifest.json"
    if manifest.exists():
        records = json.loads(manifest.read_text(encoding="utf-8"))["files"]
        expected = {record["file"]: record for record in records}
        actual = {p.relative_to(destination).as_posix(): p for p in destination.rglob("*")
                  if p.is_file() and p.suffix.casefold() == ".pdf"}
        if len(expected) != len(records) or set(expected) != set(actual):
            raise ValueError("Manifest does not match the input files")
        for name, source in actual.items():
            if c.sha256_file(source) != expected[name]["prepared_sha256"]:
                raise ValueError("Input checksum does not match manifest")
    return sorted(destination.rglob("*"), key=lambda p: p.as_posix())


def api_json(path, token, data=None):
    # Credentials are sent only to the GitHub API, never to download redirects.
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "pdf-file-conversions",
               "X-GitHub-Api-Version": "2022-11-28"}
    if token:
        headers["Authorization"] = "Bearer " + token
    payload = json.dumps(data).encode() if data is not None else None
    if payload:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request("https://api.github.com" + path, data=payload, headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.load(response)


def download_input(repository, tag, asset_name, token, destination):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid repository name")
    release = api_json(f"/repos/{repository}/releases/tags/{urllib.parse.quote(tag, safe='')}", token)
    assets = [a for a in release["assets"] if a["name"] == asset_name]
    if len(assets) != 1 or not asset_name.lower().endswith(".zip"):
        raise ValueError("Select exactly one ZIP asset from this repository's input Release")
    asset = assets[0]
    if not 0 < asset["size"] <= MAX_ARCHIVE:
        raise ValueError("Input ZIP is empty or exceeds the archive size limit")
    url = urllib.parse.urlsplit(asset["browser_download_url"])
    if (url.scheme != "https" or url.netloc != "github.com" or
            not url.path.startswith(f"/{repository}/releases/download/")):
        raise ValueError("Input must be a Release asset from this repository")
    request = urllib.request.Request(asset["browser_download_url"], headers={"User-Agent": "pdf-file-conversions"})
    count = 0
    with urllib.request.urlopen(request, timeout=180) as response, Path(destination).open("xb") as out:
        while block := response.read(1024 * 1024):
            count += len(block)
            if count > asset["size"] or count > MAX_ARCHIVE:
                raise ValueError("Downloaded input exceeded the expected size")
            out.write(block)
    if count != asset["size"]:
        raise ValueError("Downloaded input is incomplete")
    digest = asset.get("digest")
    if digest and digest != "sha256:" + c.sha256_file(destination):
        raise ValueError("Release asset checksum mismatch")
    return {"release_tag": tag, "asset_name": asset_name, "asset_id": asset["id"],
            "archive_bytes": count, "archive_sha256": c.sha256_file(destination)}


def package_results(work, destination, run_info):
    """Publish an allowlisted results tree. Originals and source code are excluded."""
    work, destination = Path(work), Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        bundle.writestr("RUN_INFO.json", json.dumps(run_info, indent=2) + "\n")
        bundle.writestr("START_HERE.txt", "Open REPORTS / run folder / OPEN REPORT.html.\n"
                        "PILOT PDFs require visual/device review before website use.\n"
                        "REVIEW files are excluded from automatic approval.\n")
        for folder in sorted(ALLOWED_OUTPUTS):
            for path in sorted((work / folder).rglob("*")):
                if path.is_symlink():
                    raise ValueError("Symlink found in output tree")
                if path.is_file():
                    if path.suffix.lower() not in {".pdf", ".json", ".csv", ".html", ".jpg", ".txt"}:
                        raise ValueError("Unexpected result file type")
                    bundle.write(path, path.relative_to(work).as_posix())
    return c.sha256_file(destination)


def publish_results(repository, token, archive, checksum_file, run_info):
    run_id = os.environ["GITHUB_RUN_ID"]
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    tag = f"results-{run_id}-{attempt}"
    release = api_json(f"/repos/{repository}/releases", token, {
        "tag_name": tag, "target_commitish": os.environ["GITHUB_SHA"],
        "name": f"PDF pilot results {run_id} (attempt {attempt})", "make_latest": "false",
        "body": f"Pilot results: {run_info['pass_count']} PASS, {run_info['review_count']} REVIEW.\n\n"
                f"Source: `{run_info['input']['release_tag']}`. Automated checks do not confirm physical device review.\n\n"
                f"Workflow: https://github.com/{repository}/actions/runs/{run_id}\n\n"
                "Download the ZIP, extract it, and open the HTML report. Keep REVIEW files out of the website."
    })
    for file in (Path(archive), Path(checksum_file)):
        url = (f"https://uploads.github.com/repos/{repository}/releases/{release['id']}/assets?name="
               + urllib.parse.quote(file.name, safe=""))
        request = urllib.request.Request(url, data=file.read_bytes(), method="POST", headers={
            "Authorization": "Bearer " + token, "Content-Type": "application/octet-stream",
            "User-Agent": "pdf-file-conversions", "X-GitHub-Api-Version": "2022-11-28"})
        with urllib.request.urlopen(request, timeout=180) as response:
            json.load(response)
    return release["html_url"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="Local testing only; skips GitHub input download")
    parser.add_argument("--tag", default=os.environ.get("INPUT_TAG", "inputs-test-001"))
    parser.add_argument("--asset", default=os.environ.get("INPUT_ASSET", "test-inputs.zip"))
    parser.add_argument("--work", type=Path, default=HERE / "work")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    c.validate_dependencies()
    repository, token = os.environ.get("GITHUB_REPOSITORY", "local/test"), os.environ.get("GH_TOKEN", "")
    if args.work.exists():
        raise ValueError("Work folder already exists; choose a new empty folder")
    args.work.mkdir(parents=True)
    source = args.archive
    input_info = {"release_tag": "local-test", "archive_sha256": c.sha256_file(source)} if source else None
    if source is None:
        source = args.work / "input.zip"
        input_info = download_input(repository, args.tag, args.asset, token, source)
    raw = args.work / "downloaded-inputs"
    extract_inputs(source, raw)
    for name in ("settings.json", "converter.py"):
        shutil.copyfile(HERE / name, args.work / name)
    c.create_folders(args.work)
    preparation = []
    for pdf in sorted(p for p in raw.rglob("*") if p.suffix.casefold() == ".pdf"):
        relative = pdf.relative_to(raw)
        print("Preparing upload metadata:", relative, flush=True)
        record = prepare_copy(pdf, args.work / "ORIGINALS" / relative)
        record["file"] = relative.as_posix()
        preparation.append(record)
    settings = c.load_settings(args.work)
    with c.exclusive_run(args.work):
        status = c.run_conversion(args.work, settings, "pilot")
    report_path, summary = c.latest_pilot(args.work)
    c.write_json(report_path.parent / "metadata-preparation.json", {"files": preparation})
    info = {"schema": 1, "mode": "pilot", "input": input_info,
            "repository": repository, "run_id": os.environ.get("GITHUB_RUN_ID"),
            "commit": os.environ.get("GITHUB_SHA"), "fingerprint": summary["fingerprint"],
            "device_review_confirmed": False, "minimum_pilot_passes": settings["minimum_pilot_passes"],
            "pass_count": sum(r["result"] == "PASS" for r in summary["files"]),
            "review_count": sum(r["result"] != "PASS" for r in summary["files"]),
            "selected_count": summary["selected_count"], "available_count": summary["available_count"]}
    archive = args.work.parent / "output-results" / "pdf-conversion-results.zip"
    digest = package_results(args.work, archive, info)
    checksum = archive.with_name("SHA256SUMS.txt")
    checksum.write_text(f"{digest}  {archive.name}\n", encoding="utf-8")
    print(f"RESULT: {info['pass_count']} PASS, {info['review_count']} REVIEW; {archive.stat().st_size:,} result bytes")
    if args.publish:
        result_url = publish_results(repository, token, archive, checksum, info)
        print("Results:", result_url)
        step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if step_summary:
            Path(step_summary).write_text(f"{info['pass_count']} PASS, {info['review_count']} REVIEW. [Download results]({result_url}).\n"
                                         "\nPhysical device review is still required.\n", encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
