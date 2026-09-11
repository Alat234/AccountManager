"""Local RK document discovery; no browser, settings, or UI dependencies."""
from dataclasses import dataclass
from pathlib import Path

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def upload_file_error(path: Path) -> str:
    if not path.is_file() or path.stat().st_size == 0:
        return f'Missing or empty file: {path.name}'
    if path.suffix.lower() not in {'.pdf', '.png', '.jpg', '.jpeg'}:
        return f'Unsupported file format: {path.name}'
    if path.stat().st_size >= MAX_UPLOAD_BYTES:
        return f'File must be smaller than 10 MB: {path.name}'
    return ''


@dataclass(frozen=True)
class RKFileChoices:
    pdfs: tuple[Path, ...]
    screenshots: tuple[Path, ...]


def discover_rk_files(account_dir: Path) -> RKFileChoices:
    files = [p for p in account_dir.iterdir() if p.is_file()]
    pdfs = sorted((p for p in files if p.suffix.lower() == '.pdf'), key=lambda p: p.name.lower())
    screenshots = sorted(
        (p for p in files if p.suffix.lower() in {'.png', '.jpg', '.jpeg'}),
        key=lambda p: p.name.lower(), reverse=True,
    )
    return RKFileChoices(tuple(pdfs), tuple(screenshots))


def submission_files(pdf: Path | list[Path] | tuple[Path, ...] | None, screenshots: list[Path]) -> dict:
    if len(screenshots) > 2:
        raise ValueError('Choose at most two deposit screenshots.')
    pdfs = list(dict.fromkeys([pdf] if isinstance(pdf, Path) else (pdf or [])))
    missing = []
    if not pdfs:
        missing.append('Bank statement PDF')
    if not screenshots:
        missing.append('Deposit screenshots (use Find RK Deposits / Make Deposit Screenshot)')
    unavailable = set()
    invalid = []
    for path in pdfs + screenshots:
        if not path.is_file() or path.stat().st_size == 0:
            missing.append(f'Missing or empty file: {path.name}')
            unavailable.add(path)
        elif error := upload_file_error(path):
            invalid.append(error)
    available_pdfs = [p for p in pdfs if p not in unavailable]
    return {'bank_statement_paths': available_pdfs,
            'bank_statement_path': available_pdfs[0] if available_pdfs else None,
            'deposit_screenshot_paths': [p for p in dict.fromkeys(screenshots) if p not in unavailable],
            'missing': missing, 'invalid': invalid}
