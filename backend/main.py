
import os
import re
import time
import uuid
import json
import logging
import unicodedata
from pathlib import Path
from io import BytesIO
from typing import Any, Optional

import fitz
import pytesseract
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
from dotenv import load_dotenv

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

try:
    from google import genai
except ImportError:
    genai = None


# =========================================================
# 1. CONFIGURATION
# =========================================================

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()

MAX_FILE_SIZE = 25 * 1024 * 1024
MAX_PDF_PAGES = 30
MAX_TEXT_CHARS = 50000
MAX_RETRIES = 3
OCR_LANGUAGE = os.getenv("OCR_LANGUAGE", "eng")

TESSERACT_EXE = os.getenv(
    "TESSERACT_CMD",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe"
)

if Path(TESSERACT_EXE).exists():
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_EXE

logger = logging.getLogger("notice2action")


# =========================================================
# 2. PYDANTIC MODELS
# =========================================================

class ExtractedTextRequest(BaseModel):
    text: str = ""
    extracted_text: str = ""
    filename: str = "notification.pdf"

    def get_notification_text(self) -> str:
        return (self.text or "").strip() or (
            self.extracted_text or ""
        ).strip()


class EligibilityMatchRequest(BaseModel):
    notification_analysis: dict[str, Any]
    student_profile: dict[str, Any]
    scheme_name: Optional[str] = None
    analysis_mode: Optional[str] = "auto"


class ImportantDate(BaseModel):
    event: str = ""
    date: str = ""
    description: str = ""


class SchemeCriterion(BaseModel):
    criterion: str
    source_evidence: str = ""
    confidence: str = "medium"
    verification_required: bool = True


class SchemeEligibility(BaseModel):
    scheme_name: str
    description: str = "Not specified in the notification."
    extraction_status: str = "More information required"
    eligibility_criteria: list[SchemeCriterion] = Field(default_factory=list)
    benefits: list[str] = Field(default_factory=list)
    important_dates: list[ImportantDate] = Field(default_factory=list)
    application_link: str = ""
    notes: list[str] = Field(default_factory=list)


class SchemeWiseExtraction(BaseModel):
    schemes: list[SchemeEligibility] = Field(default_factory=list)


# =========================================================
# 3. FASTAPI APPLICATION
# =========================================================

app = FastAPI(
    title="NOTICE2ACTION AI API",
    description="AI-powered scholarship notification analysis and eligibility matching.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"]
)


# =========================================================
# 4. GENERAL HELPERS
# =========================================================

def normalize_text(value: Any) -> str:
    if value is None:
        return ""

    value = unicodedata.normalize("NFKC", str(value))
    value = value.lower()
    value = value.replace("’", "'")
    value = value.replace("–", "-").replace("—", "-")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def clean_ocr_text(text: str) -> str:
    text = (text or "").replace("\x00", " ")
    text = text.replace("\u00ad", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def unique_strings(values: list) -> list:
    result = []
    seen = set()

    for value in values:
        item = re.sub(
            r"\s+",
            " ",
            str(value or "")
        ).strip(" \t-•")

        key = normalize_text(item)

        if item and key not in seen:
            seen.add(key)
            result.append(item)

    return result


def safe_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def profile_boolean(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value

    if value is None:
        return None

    value = normalize_text(value)

    if value in ["yes", "true", "1", "y", "approved"]:
        return True

    if value in ["no", "false", "0", "n", "not approved"]:
        return False

    return None


def safe_filename(filename: str) -> str:
    filename = Path(filename or "notification.pdf").name
    filename = re.sub(r"[^A-Za-z0-9._-]", "_", filename)

    return filename[:150] or "notification.pdf"


# =========================================================
# 5. OCR AND PDF EXTRACTION
# =========================================================

def preprocess_image(image: Image.Image) -> Image.Image:
    image = ImageOps.exif_transpose(image)
    image = image.convert("L")
    image = ImageEnhance.Contrast(image).enhance(1.7)
    image = ImageEnhance.Sharpness(image).enhance(1.5)
    image = image.filter(ImageFilter.MedianFilter(size=3))

    return image


def ocr_image(image: Image.Image) -> str:
    try:
        processed = preprocess_image(image)

        text = pytesseract.image_to_string(
            processed,
            lang=OCR_LANGUAGE,
            config="--oem 3 --psm 6"
        )

        return clean_ocr_text(text)

    except Exception as error:
        logger.warning("OCR error: %s", error)
        return ""


def extract_page_text(page: fitz.Page):
    digital_text = clean_ocr_text(
        page.get_text("text") or ""
    )

    image_coverage = 0.0

    try:
        page_area = max(
            page.rect.width * page.rect.height,
            1
        )

        image_rects = []

        for image_info in page.get_images(full=True):
            image_rects.extend(
                page.get_image_rects(image_info[0])
            )

        if image_rects:
            image_area = sum(
                rect.width * rect.height
                for rect in image_rects
            )

            image_coverage = min(
                image_area / page_area,
                1.0
            )

    except Exception as error:
        logger.warning("Image coverage error: %s", error)

    should_ocr = (
        len(digital_text) < 80
        or image_coverage > 0.35
    )

    if not should_ocr:
        return digital_text, False

    try:
        pix = page.get_pixmap(
            matrix=fitz.Matrix(2, 2),
            alpha=False
        )

        with Image.open(
            BytesIO(pix.tobytes("png"))
        ) as image:
            ocr_text = ocr_image(image.copy())

        # Prefer OCR only when it provides more usable text.
        if len(ocr_text) > len(digital_text):
            return ocr_text, True

        if digital_text:
            return digital_text, False

        return ocr_text, bool(ocr_text)

    except Exception as error:
        logger.warning("Page extraction error: %s", error)
        return digital_text, False


def extract_pdf_text(data: bytes):
    try:
        document = fitz.open(
            stream=data,
            filetype="pdf"
        )
    except Exception as error:
        raise HTTPException(
            status_code=400,
            detail=f"Unable to open PDF: {error}"
        )

    try:
        if document.page_count == 0:
            raise HTTPException(
                status_code=400,
                detail="PDF contains no pages."
            )

        if document.page_count > MAX_PDF_PAGES:
            raise HTTPException(
                status_code=400,
                detail=f"Maximum {MAX_PDF_PAGES} PDF pages allowed."
            )

        page_texts = []
        ocr_pages = []
        unreadable_pages = []

        for index, page in enumerate(document):
            text, used_ocr = extract_page_text(page)

            page_texts.append(text)

            if used_ocr:
                ocr_pages.append(index + 1)

            if len(text.strip()) < 15:
                unreadable_pages.append(index + 1)

        full_text = clean_ocr_text(
            "\n\n".join(page_texts)
        )

        truncated = len(full_text) > MAX_TEXT_CHARS

        if truncated:
            full_text = full_text[:MAX_TEXT_CHARS]

        return {
            "text": full_text,
            "total_pages": len(page_texts),
            "ocr_used": bool(ocr_pages),
            "ocr_pages": ocr_pages,
            "unreadable_pages": unreadable_pages,
            "truncated": truncated,
            "page_texts": page_texts
        }

    finally:
        document.close()


# =========================================================
# 6. GEMINI CLIENT AND RETRY
# =========================================================

def get_gemini_client():
    if not GEMINI_API_KEY or genai is None:
        return None

    try:
        return genai.Client(api_key=GEMINI_API_KEY)
    except Exception as error:
        logger.error("Gemini client initialization failed: %s", error)
        return None


def strip_json_fence(text: str) -> str:
    text = (text or "").strip()

    text = re.sub(
        r"^```(?:json)?\s*",
        "",
        text,
        flags=re.I
    )

    text = re.sub(r"\s*```$", "", text)

    start = text.find("{")
    end = text.rfind("}")

    if start >= 0 and end > start:
        return text[start:end + 1]

    return text


def generate_with_retry(client, prompt: str) -> str:
    if client is None:
        raise RuntimeError("Gemini API client is not configured.")

    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config={
                    "response_mime_type": "application/json"
                }
            )

            result = getattr(response, "text", None)

            if not result or not result.strip():
                raise RuntimeError("Gemini returned an empty response.")

            return result.strip()

        except Exception as error:
            last_error = error
            logger.warning(
                "Gemini attempt %s failed: %s",
                attempt + 1,
                error
            )

            if attempt < MAX_RETRIES - 1:
                time.sleep(2 ** attempt)

    raise RuntimeError(
        f"Gemini request failed after {MAX_RETRIES} attempts: {last_error}"
    )


# =========================================================
# 7. ROOT AND HEALTH ENDPOINTS
# =========================================================

@app.get("/")
async def root():
    return {
        "success": True,
        "application": "NOTICE2ACTION AI",
        "version": "1.0.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health():
    try:
        pytesseract.get_tesseract_version()
        tesseract_available = True
    except Exception:
        tesseract_available = False

    return {
        "success": True,
        "status": "healthy",
        "gemini_configured": bool(GEMINI_API_KEY),
        "gemini_package_available": genai is not None,
        "tesseract_available": tesseract_available
    }


# =========================================================
# 8. PDF UPLOAD ENDPOINT
# =========================================================

@app.post("/upload-notification")
async def upload_notification(file: UploadFile = File(...)):
    filename = file.filename or "notification.pdf"

    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Please upload a PDF file."
        )

    # Read at most one byte above the limit.
    # This prevents loading an oversized upload completely into memory.
    data = await file.read(MAX_FILE_SIZE + 1)

    if not data:
        raise HTTPException(
            status_code=400,
            detail="Uploaded file is empty."
        )

    if len(data) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=413,
            detail="PDF exceeds the 25 MB upload limit."
        )

    result = await run_in_threadpool(
        extract_pdf_text,
        data
    )

    stored_name = (
        f"{uuid.uuid4().hex}_"
        f"{safe_filename(filename)}"
    )

    try:
        (UPLOAD_DIR / stored_name).write_bytes(data)
    except Exception as error:
        logger.warning("File saving error: %s", error)

    return {
        "success": True,
        "filename": filename,
        "total_pages": result["total_pages"],
        "ocr_used": result["ocr_used"],
        "ocr_pages": result["ocr_pages"],
        "unreadable_pages": result["unreadable_pages"],
        "truncated": result["truncated"],
        "extracted_text": result["text"],
        "page_texts": result["page_texts"],
        "message": "PDF text extraction completed."
    }


# =========================================================
# 9. SCHOLARSHIP SCHEME DETECTION
# =========================================================

SCHEME_PATTERNS = [
    ("AICTE Pragati Scholarship",
     r"\bpragati\s+(?:scholarship|scheme)\b"),

    ("AICTE Saksham Scholarship",
     r"\bsaksham\s+(?:scholarship|scheme)\b"),

    ("AICTE Swanath Scholarship",
     r"\bswanath\s+(?:scholarship|scheme)\b"),

    ("Ishan Uday Special Scholarship Scheme",
     r"\bishan\s+uday\b"),

    ("National Scholarship for Post Graduate Studies",
     r"\bnational\s+scholarship\s+for\s+post[- ]graduate\s+studies\b"),

    ("Post Matric Scholarship",
     r"\bpost[- ]matric(?:ulation)?\s+scholarship\b"),

    ("Pre Matric Scholarship",
     r"\bpre[- ]matric(?:ulation)?\s+scholarship\b"),

    ("Central Sector Scheme of Scholarship",
     r"\bcentral\s+sector\s+scheme\b.{0,100}\bscholarship\b"),

    ("PM YASASVI Scholarship",
     r"\bpm\s+yasasvi\b|\byasasvi\s+scholarship\b"),

    ("INSPIRE Scholarship",
     r"\binspire\s+(?:scholarship|fellowship|scheme)\b"),

    ("PhD Fellowship",
     r"\bph\.?\s*d\.?\s+fellowships?\b"),

    ("Scholarship for Students with Disabilities",
     r"\bscholarship\s+for\s+(?:students|persons)\s+with\s+disabilities\b"),

    ("Minority Merit-cum-Means Scholarship",
     r"\bmerit[- ]cum[- ]means\s+scholarship\b")
]


def split_notification_pages(text: str):
    chunks = re.split(
        r"\n\s*(?:page\s*)?\d+\s*\n",
        text,
        flags=re.I
    )

    return [
        chunk.strip()
        for chunk in chunks
        if chunk.strip()
    ] or [text]


def detect_scholarship_schemes(text: str):
    """
    Detect only recognised, explicitly named scholarship schemes.
    Generic document headings and portal references are not schemes.
    """

    normalized = normalize_text(text)
    found = []

    for name, pattern in SCHEME_PATTERNS:
        matches = list(
            re.finditer(pattern, normalized, flags=re.I)
        )

        if not matches:
            continue

        found.append({
            "scheme_name": name,
            "confidence": "high",
            "verification_required": False,
            "mentions": len(matches)
        })

    found.sort(
        key=lambda item: item["mentions"],
        reverse=True
    )

    return found


# =========================================================
# 10. GENERAL AI ANALYSIS PROMPT
# =========================================================

def build_analysis_prompt(text: str):
    return f"""
You are NOTICE2ACTION AI.

Analyze the supplied official scholarship notification.

Use ONLY information supported by the supplied notification.

STRICT RULES:

1. Never invent eligibility rules.
2. Never invent dates, amounts or application links.
3. Do not treat document headings as separate scholarship schemes.
4. Extract only schemes explicitly named in the document.
5. Do not treat NSP, UGC, AICTE or ministry names as scholarships.
6. Do not mix eligibility conditions between different schemes.
7. Use "Not specified in the notification" when information is absent.
8. Preserve the meaning of the original notification.
9. Do not assume a purpose that is not supported by the document.

Return valid JSON only.

Required JSON structure:

{{
    "notice_title": "",
    "notification_type": "",
    "issuing_authority": "",
    "scholarship_scheme": "",
    "purpose": "",
    "summary": "",
    "scholarship_names": [],
    "eligibility_criteria": [],
    "benefits": [],
    "required_documents": [],
    "application_process": [],
    "important_dates": [
        {{
            "event": "",
            "date": "",
            "description": ""
        }}
    ],
    "application_link": "",
    "contact_details": [],
    "warnings": []
}}

For notification_type, identify whether the document is a
scholarship notification, circular, guideline, advertisement,
office memorandum, announcement or another clearly supported type.

For scholarship_scheme, provide the explicitly named scheme or
schemes. Do not invent a scheme name from a general heading.

For purpose, briefly explain the stated objective of the notification.
If no objective is stated, return "Not specified in the notification."

NOTIFICATION TEXT:

{text[:MAX_TEXT_CHARS]}
"""


# =========================================================
# 11. SCHEME-WISE ELIGIBILITY EXTRACTION
# =========================================================

def build_scheme_prompt(text: str, detected_schemes: list):
    names = [
        item.get("scheme_name", "")
        for item in detected_schemes
    ]

    return f"""
You are NOTICE2ACTION AI, a scholarship notification
information extraction system.

Extract information separately for every detected scheme.

STRICT RULES:

1. Use ONLY the supplied notification.
2. Never invent eligibility conditions.
3. Never mix conditions between schemes.
4. Extract each eligibility condition separately.
5. Preserve the exact supporting sentence as source_evidence.
6. Evidence must come from the supplied notification.
7. Do not use general NSP announcements as scheme-specific criteria.
8. Extract benefits only when explicitly stated.
9. Extract dates only when explicitly stated.
10. Never invent application links.
11. If information is missing, return an empty string or list.
12. Use high confidence only for clearly stated conditions.
13. Use medium confidence for partially clear conditions.
14. Use low confidence when OCR or wording is uncertain.
15. Set verification_required to true for ambiguous conditions.

A sentence such as "Interested and eligible students are advised
to register and apply on the NSP portal" is an application
instruction, NOT an eligibility criterion.

Return valid JSON only:

{{
    "schemes": [
        {{
            "scheme_name": "",
            "description": "",
            "extraction_status": "Extracted",
            "eligibility_criteria": [
                {{
                    "criterion": "",
                    "source_evidence": "",
                    "confidence": "high",
                    "verification_required": false
                }}
            ],
            "benefits": [],
            "important_dates": [
                {{
                    "event": "",
                    "date": "",
                    "description": ""
                }}
            ],
            "application_link": "",
            "notes": []
        }}
    ]
}}

DETECTED SCHOLARSHIPS:
{json.dumps(names, ensure_ascii=False)}

NOTIFICATION TEXT:
{text[:MAX_TEXT_CHARS]}
"""


def empty_scheme_result(name: str):
    return {
        "scheme_name": name,
        "description": "",
        "extraction_status": "More information required",
        "eligibility_criteria": [],
        "benefits": [],
        "important_dates": [],
        "application_link": "",
        "notes": [
            "No reliable scheme-specific details could be extracted."
        ]
    }


def _scheme_aliases(scheme_name: str) -> list:
    name = normalize_text(scheme_name)

    known = {
        "pragati": ["pragati"],
        "saksham": ["saksham"],
        "swanath": ["swanath"],
        "ishan uday": ["ishan uday"],
        "post matric": ["post matric", "post-matric"],
        "pre matric": ["pre matric", "pre-matric"],
        "yasasvi": ["yasasvi"],
        "disabilities": [
            "students with disabilities",
            "disabilities"
        ],
        "merit-cum-means": [
            "merit-cum-means",
            "merit cum means"
        ],
        "phd": ["phd fellowship", "phd fellowships"],
        "central sector": ["central sector scheme"],
        "post graduate studies": [
            "national scholarship for post graduate studies"
        ]
    }

    aliases = []

    for key, values in known.items():
        if key in name:
            aliases.extend(values)

    return aliases or [name]


def _criteria_for_scheme_context(
    text: str,
    scheme_name: str,
    all_schemes: list
) -> list:
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]

    aliases = _scheme_aliases(scheme_name)
    other_aliases = []

    for other in all_schemes:
        if normalize_text(
            other.get("scheme_name", "")
        ) == normalize_text(scheme_name):
            continue

        other_aliases.extend(
            _scheme_aliases(other.get("scheme_name", ""))
        )

    start_indexes = [
        i for i, line in enumerate(lines)
        if any(
            alias in normalize_text(line)
            for alias in aliases
        )
    ]

    if not start_indexes:
        return []

    collected = []

    for start in start_indexes:
        for j in range(start, min(start + 12, len(lines))):
            normalized_line = normalize_text(lines[j])

            if j > start and any(
                alias in normalized_line
                for alias in other_aliases
            ):
                break

            collected.append(lines[j])

    context = "\n".join(dict.fromkeys(collected))

    return extract_rule_based_criteria(context)


def extract_source_evidence(
    criterion: str,
    source_text: str
) -> str:
    """
    Finds a likely source passage. This is heuristic evidence,
    not proof that the passage semantically supports the criterion.
    """

    if not criterion or not source_text:
        return ""

    stop_words = {
        "the", "a", "an", "to", "of", "and", "or", "in",
        "for", "is", "are", "be", "with", "from", "who",
        "must", "maximum", "minimum", "students"
    }

    criterion_words = {
        word for word in re.findall(
            r"\b[a-z0-9]+\b",
            normalize_text(criterion)
        )
        if word not in stop_words and len(word) > 1
    }

    if not criterion_words:
        return ""

    lines = [
        line.strip()
        for line in source_text.splitlines()
        if line.strip()
    ]

    candidates = []

    for i in range(len(lines)):
        for size in range(1, min(5, len(lines) - i + 1)):
            passage = "\n".join(lines[i:i + size]).strip()

            if passage and len(passage) <= 1800:
                candidates.append(passage)

    for paragraph in re.split(r"\n\s*\n", source_text):
        paragraph = paragraph.strip()

        if paragraph and len(paragraph) <= 1800:
            candidates.append(paragraph)

    best_passage = ""
    best_score = 0.0

    for passage in candidates:
        passage_words = set(
            re.findall(
                r"\b[a-z0-9]+\b",
                normalize_text(passage)
            )
        )

        if not passage_words:
            continue

        common = criterion_words & passage_words
        score = len(common) / len(criterion_words)

        if score > best_score or (
            score == best_score
            and best_passage
            and len(passage) < len(best_passage)
        ):
            best_score = score
            best_passage = passage

    if best_score < 0.40:
        return ""

    return best_passage[:1800]


def is_valid_eligibility_criterion(criterion: str) -> bool:
    text = normalize_text(criterion)

    if not text or len(text.split()) < 4:
        return False

    instruction_phrases = [
        "interested and eligible students are advised",
        "register and apply",
        "on the nsp portal",
        "within the stipulated timeline",
        "last dates for",
        "scheme-wise details"
    ]

    if any(phrase in text for phrase in instruction_phrases):
        return False

    eligibility_patterns = [
        r"\bannual family income\b",
        r"\bfamily income\b",
        r"\bincome limit\b",
        r"\bsc\b|\bst\b|\bobc\b|\bews\b",
        r"\bminority\b|\bebc\b",
        r"\bcategory\b",
        r"\bgirls?\b|\bfemales?\b|\bwomen\b",
        r"\bmarks\b|\bpercentage\b|\bcgpa\b",
        r"\bage\b",
        r"\bdomicile\b|\bresident of\b",
        r"\bcourse\b|\bdegree\b|\bdiploma\b",
        r"\bfirst year\b|\bsecond year\b",
        r"\bdifferently[- ]abled\b|\bdisability\b",
        r"\baicte[- ]approved\b",
        r"\brecognized institution\b",
        r"\btechnical\b",
        r"\blateral entry\b",
        r"\bparent\b|\bparents\b",
        r"\badmitted\b|\benrolled\b"
    ]

    return any(
        re.search(pattern, text)
        for pattern in eligibility_patterns
    )



def extract_rule_based_criteria(text: str) -> list[str]:
    """
    Extract preliminary eligibility statements from notification text.

    This conservative fallback returns source-derived text snippets only.
    It does not invent requirements or decide whether a student is eligible.
    """
    if not text or not str(text).strip():
        return []

    source = clean_ocr_text(str(text))
    candidates = []

    # Join wrapped PDF lines, but keep separate paragraphs distinct.
    for paragraph in re.split(r"\n\s*\n", source):
        paragraph = re.sub(r"\s+", " ", paragraph).strip()
        if not paragraph:
            continue

        # Do not split common currency abbreviations such as "Rs. 8 lakh".
        paragraph = re.sub(r"(?i)\bRs\.\s*", "RUPEES ", paragraph)
        parts = re.split(r"(?<=[!?])\s+|(?<!\.)\.\s+|;\s*", paragraph)
        candidates.extend(parts)

    # Individual lines capture bullet lists that have no sentence punctuation.
    for line in source.splitlines():
        line = re.sub(r"\s+", " ", line).strip()
        line = re.sub(r"^\s*(?:[-•▪●]|\(?\d+[.)])\s*", "", line)
        if line:
            candidates.append(line)

    results = []
    seen = set()

    for candidate in candidates:
        criterion = re.sub(r"\s+", " ", candidate).strip(" \t\r\n-•;:")
        criterion = re.sub(r"^\(?\d+[.)]\s*", "", criterion).strip()
        criterion = re.sub(r"(?i)\bRUPEES\b", "Rs.", criterion)
        criterion = re.sub(
            r"(?i)^(?:eligibility(?:\s+criteria)?|criteria)\s*:\s*",
            "",
            criterion
        ).strip()

        if not criterion or len(criterion) > 700:
            continue
        if not is_valid_eligibility_criterion(criterion):
            continue

        key = normalize_text(criterion).strip(" .!?;:")
        # Paragraph sentences are considered first, so skip shorter line
        # fragments already represented by a complete extracted sentence.
        if key in seen or any(key in existing for existing in seen):
            continue

        seen.add(key)
        results.append(criterion)

    return results

# Single authoritative cleaner: no duplicate definition.
def clean_eligibility_criteria(
    criteria: Any,
    source_text: str
):
    cleaned = []
    source_norm = normalize_text(source_text)

    for item in safe_list(criteria):
        if isinstance(item, str):
            criterion = item.strip()

            if not criterion or not is_valid_eligibility_criterion(criterion):
                continue

            evidence = extract_source_evidence(
                criterion,
                source_text
            )

            cleaned.append({
                "criterion": criterion,
                "source_evidence": evidence,
                "confidence": "low",
                "verification_required": True
            })
            continue

        if not isinstance(item, dict):
            continue

        criterion = str(
            item.get("criterion")
            or item.get("text")
            or item.get("requirement")
            or item.get("condition")
            or ""
        ).strip()

        if not criterion or not is_valid_eligibility_criterion(criterion):
            continue

        evidence = str(
            item.get("source_evidence")
            or item.get("evidence")
            or item.get("evidence_text")
            or item.get("source_text")
            or ""
        ).strip()

        # Exact evidence must occur in the original notification.
        evidence_is_exact = (
            bool(evidence)
            and normalize_text(evidence) in source_norm
        )

        if not evidence_is_exact:
            evidence = extract_source_evidence(
                criterion,
                source_text
            )

        confidence = normalize_text(
            item.get("confidence", "medium")
        )

        if confidence not in ["high", "medium", "low"]:
            confidence = "low"

        # Heuristically selected evidence cannot retain high confidence.
        if not evidence_is_exact:
            confidence = "low"

        verification_required = (
            item.get("verification_required") is True
            or confidence == "low"
            or not evidence
        )

        cleaned.append({
            "criterion": criterion,
            "source_evidence": evidence,
            "confidence": confidence,
            "verification_required": verification_required
        })

    unique = []
    seen = set()

    for item in cleaned:
        key = normalize_text(item["criterion"])

        if key not in seen:
            seen.add(key)
            unique.append(item)

    return unique


def fallback_scheme_results(
    text: str,
    detected_schemes: list
):
    results = []

    for detected in detected_schemes:
        name = detected.get(
            "scheme_name",
            "Unnamed scholarship"
        )

        result = empty_scheme_result(name)

        if len(detected_schemes) == 1:
            criteria = extract_rule_based_criteria(text)
        else:
            criteria = _criteria_for_scheme_context(
                text,
                name,
                detected_schemes
            )

        result["eligibility_criteria"] = clean_eligibility_criteria(
            criteria,
            text
        )

        if result["eligibility_criteria"]:
            result["extraction_status"] = "Rule-based extraction"
            result["notes"] = [
                "Preliminary criteria were extracted from the notification. "
                "Verify the original official notice."
            ]

        results.append(result)

    return {"schemes": results}


def extract_scheme_wise_eligibility(
    text: str,
    detected_schemes: list
):
    if not detected_schemes:
        return {"schemes": []}

    client = get_gemini_client()

    if client is None:
        return fallback_scheme_results(text, detected_schemes)

    try:
        prompt = build_scheme_prompt(text, detected_schemes)
        raw = generate_with_retry(client, prompt)
        parsed = json.loads(strip_json_fence(raw))

        if not isinstance(parsed, dict):
            raise ValueError("Gemini response is not a JSON object.")

        extracted_schemes = safe_list(parsed.get("schemes"))

    except Exception as error:
        logger.error("Scheme extraction AI error: %s", error)
        return fallback_scheme_results(text, detected_schemes)

    normalized = []

    for detected in detected_schemes:
        name = detected.get(
            "scheme_name",
            "Unnamed scholarship"
        )

        matching = next(
            (
                item for item in extracted_schemes
                if isinstance(item, dict)
                and normalize_text(item.get("scheme_name", "")) ==
                normalize_text(name)
            ),
            None
        )

        # Allow a unique partial name match for minor AI naming variations.
        if matching is None:
            possible = [
                item for item in extracted_schemes
                if isinstance(item, dict)
                and (
                    normalize_text(name) in normalize_text(item.get("scheme_name", ""))
                    or normalize_text(item.get("scheme_name", "")) in normalize_text(name)
                )
            ]

            if len(possible) == 1:
                matching = possible[0]

        if not isinstance(matching, dict):
            matching = empty_scheme_result(name)

        result = empty_scheme_result(name)

        result["description"] = str(
            matching.get("description", "")
        ).strip()

        result["eligibility_criteria"] = clean_eligibility_criteria(
            matching.get("eligibility_criteria", []),
            text
        )

        result["benefits"] = unique_strings(
            safe_list(matching.get("benefits", []))
        )

        for date_item in safe_list(matching.get("important_dates", [])):
            if not isinstance(date_item, dict):
                continue

            result["important_dates"].append({
                "event": str(date_item.get("event", "")).strip(),
                "date": str(date_item.get("date", "")).strip(),
                "description": str(date_item.get("description", "")).strip()
            })

        application_link = str(
            matching.get("application_link", "")
        ).strip()

        if re.match(r"^https?://", application_link, flags=re.I):
            result["application_link"] = application_link

        result["notes"] = unique_strings(
            safe_list(matching.get("notes", []))
        )

        if result["eligibility_criteria"]:
            result["extraction_status"] = "AI extraction"
        else:
            if len(detected_schemes) == 1:
                local_criteria = extract_rule_based_criteria(text)
            else:
                local_criteria = _criteria_for_scheme_context(
                    text,
                    name,
                    detected_schemes
                )

            result["eligibility_criteria"] = clean_eligibility_criteria(
                local_criteria,
                text
            )

            if result["eligibility_criteria"]:
                result["extraction_status"] = "Rule-based fallback"
                result["notes"].append(
                    "AI extraction returned no criteria. "
                    "Preliminary rule-based extraction was used. "
                    "Verify the official notice."
                )

        if not result["description"]:
            result["description"] = (
                "A scholarship scheme identified in the uploaded "
                "notification. A separate description was not extracted."
            )

        if not result["notes"]:
            result["notes"] = [
                "Extracted information should be verified against the official notice."
            ]

        normalized.append(result)

    return {"schemes": normalized}


# =========================================================
# 12. RULE-BASED FALLBACK ANALYSIS
# =========================================================

def extract_notification_title(text: str, filename: str) -> str:
    lines = [
        re.sub(r"\s+", " ", line).strip(" :-")
        for line in text.splitlines()
        if line.strip()
    ]

    for line in lines[:15]:
        if (
            len(line) >= 8
            and len(line) <= 180
            and not re.fullmatch(r"page\s+\d+", line, flags=re.I)
        ):
            return line

    return Path(filename).stem.replace("_", " ").replace("-", " ")


def detect_notification_type(text: str) -> str:
    normalized = normalize_text(text)

    if "office memorandum" in normalized:
        return "Office Memorandum"

    if "press release" in normalized:
        return "Press Release"

    if "guidelines" in normalized or "guideline" in normalized:
        return "Scholarship Guidelines"

    if "circular" in normalized:
        return "Circular"

    if "advertisement" in normalized:
        return "Advertisement"

    if (
        "notification" in normalized
        or "scholarship" in normalized
        or "fellowship" in normalized
    ):
        return "Scholarship Notification"

    return "Official Notification"


def extract_notification_purpose(text: str) -> str:
    """
    Return a purpose sentence only when the notification
    explicitly states an objective.
    """

    patterns = [
        r"[^.\n]{0,100}(?:aims to|aimed at|objective is|purpose is)"
        r"[^.\n]{10,250}[.]?",

        r"[^.\n]{0,100}(?:to provide financial assistance|"
        r"to support students|to promote education|"
        r"to encourage students)[^.\n]{10,250}[.]?"
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.I)

        if match:
            return re.sub(
                r"\s+",
                " ",
                match.group(0)
            ).strip()

    return "Not specified in the notification."


def enrich_analysis_metadata(
    analysis: dict,
    text: str,
    filename: str,
    detected_schemes: list
):
    """
    Populate basic notification information without inventing
    scholarship names or purposes.
    """

    if not analysis.get("notice_title"):
        analysis["notice_title"] = extract_notification_title(
            text,
            filename
        )

    if not analysis.get("notification_type"):
        analysis["notification_type"] = detect_notification_type(text)

    scheme_names = [
        item["scheme_name"]
        for item in detected_schemes
        if item.get("scheme_name")
    ]

    # Use the recognised scheme names as the authoritative list.
    analysis["scholarship_names"] = scheme_names

    if scheme_names:
        analysis["scholarship_scheme"] = ", ".join(scheme_names)

    elif re.search(
        r"\bscholarship|\bfellowship",
        normalize_text(text)
    ):
        analysis["scholarship_scheme"] = (
            "General scholarship information "
            "(no specific scheme identified)"
        )

    else:
        analysis["scholarship_scheme"] = (
            "Not specified in the notification."
        )

    purpose = str(analysis.get("purpose") or "").strip()

    if not purpose or normalize_text(purpose) in [
        "not specified",
        "not specified in the notification",
        "not specified in the notice"
    ]:
        purpose = extract_notification_purpose(text)

    analysis["purpose"] = purpose

    return analysis


def build_fallback_analysis(text: str, filename: str):
    detected = detect_scholarship_schemes(text)
    dates = []

    date_pattern = (
        r"(.{0,70}(?:last date|deadline|starting date|"
        r"opens on|closes on).{0,100})"
    )

    for match in re.finditer(date_pattern, text, flags=re.I):
        dates.append({
            "event": "Application date",
            "date": "",
            "description": re.sub(
                r"\s+",
                " ",
                match.group(1)
            ).strip()
        })

    analysis = {
        "notice_title": extract_notification_title(text, filename),
        "notification_type": detect_notification_type(text),
        "issuing_authority": "Not reliably identified",
        "scholarship_scheme": "",
        "purpose": extract_notification_purpose(text),
        "summary": (
            "Rule-based preliminary analysis was generated because "
            "AI analysis was unavailable. Verify all information "
            "against the original notice."
        ),
        "scholarship_names": [],
        "eligibility_criteria": extract_rule_based_criteria(text),
        "benefits": [],
        "required_documents": [],
        "application_process": [],
        "important_dates": dates[:20],
        "application_link": "",
        "contact_details": [],
        "warnings": [
            "Fallback extraction was used.",
            "Verify eligibility and dates in the official notification."
        ]
    }

    return enrich_analysis_metadata(
        analysis,
        text,
        filename,
        detected
    )


# =========================================================
# 13. ANALYZE NOTIFICATION ENDPOINT
# =========================================================

@app.post("/analyze-notification")
async def analyze_notification(request: ExtractedTextRequest):

    text = clean_ocr_text(
        request.get_notification_text()
    )

    if not text:
        raise HTTPException(
            status_code=400,
            detail="No notification text was provided. Upload the PDF again."
        )

    detected = detect_scholarship_schemes(text)

    analysis_mode = "gemini"
    client = get_gemini_client()

    # -----------------------------------------------------
    # GENERAL AI ANALYSIS
    # -----------------------------------------------------

    if client is not None:
        try:
            raw = await run_in_threadpool(
                generate_with_retry,
                client,
                build_analysis_prompt(text)
            )

            analysis = json.loads(
                strip_json_fence(raw)
            )

            if not isinstance(analysis, dict):
                raise ValueError(
                    "Gemini response is not a JSON object."
                )

        except Exception as error:
            logger.error(
                "Gemini analysis failed: %s",
                error
            )

            analysis = build_fallback_analysis(
                text,
                request.filename
            )

            analysis_mode = "rule_based_fallback"

    else:
        analysis = build_fallback_analysis(
            text,
            request.filename
        )

        analysis_mode = "rule_based_fallback"

    # -----------------------------------------------------
    # SCHEME-WISE EXTRACTION
    # -----------------------------------------------------

    try:
        scheme_extraction = await run_in_threadpool(
            extract_scheme_wise_eligibility,
            text,
            detected
        )

    except Exception as error:
        logger.error(
            "Scheme-wise extraction failed: %s",
            error
        )

        scheme_extraction = fallback_scheme_results(
            text,
            detected
        )

        if analysis_mode == "gemini":
            analysis_mode = "gemini_partial"

    # -----------------------------------------------------
    # SYNCHRONISE MAIN CRITERIA WITH SCHEME-WISE RESULTS
    # -----------------------------------------------------

    combined_criteria = []
    seen_criteria = set()

    for scheme in safe_list(
        scheme_extraction.get("schemes")
    ):
        if not isinstance(scheme, dict):
            continue

        scheme_criteria = safe_list(
            scheme.get("eligibility_criteria")
        )

        for item in scheme_criteria:
            if isinstance(item, str):
                criterion = item.strip()

            elif isinstance(item, dict):
                criterion = str(
                    item.get("criterion")
                    or item.get("text")
                    or item.get("requirement")
                    or ""
                ).strip()

            else:
                continue

            key = normalize_text(criterion)

            if criterion and key not in seen_criteria:
                seen_criteria.add(key)
                combined_criteria.append(criterion)

    # Keep the main results populated whenever scheme-wise
    # extraction successfully found criteria.
    if combined_criteria:
        analysis["eligibility_criteria"] = combined_criteria

    elif not isinstance(
        analysis.get("eligibility_criteria"),
        list
    ):
        analysis["eligibility_criteria"] = []

    # -----------------------------------------------------
    # POPULATE BASIC NOTIFICATION INFORMATION
    # -----------------------------------------------------

    analysis = enrich_analysis_metadata(
        analysis,
        text,
        request.filename,
        detected
    )

    # -----------------------------------------------------
    # EXTRACTION SUMMARY
    # -----------------------------------------------------

    total_extracted_criteria = sum(
        len(
            safe_list(
                scheme.get("eligibility_criteria")
            )
        )
        for scheme in safe_list(
            scheme_extraction.get("schemes")
        )
        if isinstance(scheme, dict)
    )

    if total_extracted_criteria > 0:
        extraction_message = (
            "Eligibility criteria were extracted. "
            "Review the scheme-wise details before matching."
        )

    elif detected:
        extraction_message = (
            "Schemes were identified, but reliable eligibility "
            "criteria could not be extracted from the notification."
        )

    else:
        extraction_message = (
            "No specific scholarship scheme was identified. "
            "This may be a general scholarship information document."
        )

    # -----------------------------------------------------
    # FINAL RESPONSE
    # -----------------------------------------------------

    return {
        "success": True,
        "filename": request.filename,
        "analysis_mode": analysis_mode,

        # Main analysis
        "analysis": analysis,

        # Basic fields also exposed at the top level
        # for frontend compatibility.
        "notification_type": analysis.get(
            "notification_type",
            "Not specified in the notification."
        ),

        "scholarship_scheme": analysis.get(
            "scholarship_scheme",
            "Not specified in the notification."
        ),

        "purpose": analysis.get(
            "purpose",
            "Not specified in the notification."
        ),

        # Scheme detection and extraction
        "detected_schemes": detected,
        "scheme_wise_extraction": scheme_extraction,

        # Extraction summary
        "total_extracted_criteria": total_extracted_criteria,

        "message": extraction_message
    }


# =========================================================
# 14. INCOME LIMIT EXTRACTION
# =========================================================

def extract_income_limit(criterion: str) -> Optional[float]:
    text = normalize_text(criterion)

    income_terms = [
        "income",
        "family income",
        "annual income",
        "parental income"
    ]

    if not any(term in text for term in income_terms):
        return None

    range_pattern = (
        r"(?:rs\.?|inr|₹)?\s*"
        r"\d[\d,]*(?:\.\d+)?\s*-\s*"
        r"\d[\d,]*(?:\.\d+)?"
    )

    if re.search(range_pattern, text):
        return None

    amount_pattern = (
        r"(?:rs\.?|inr|₹)\s*"
        r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*"
        r"(lakh|lakhs|crore|crores)?"
        r"|"
        r"([0-9]+(?:\.[0-9]+)?)\s*"
        r"(lakh|lakhs|crore|crores)"
    )

    matches = list(re.finditer(amount_pattern, text))

    if len(matches) != 1:
        return None

    match = matches[0]

    try:
        if match.group(1) is not None:
            amount = float(match.group(1).replace(",", ""))
            unit = (match.group(2) or "").lower()
        else:
            amount = float(match.group(3))
            unit = (match.group(4) or "").lower()

        if amount <= 0:
            return None

        if unit.startswith("lakh"):
            amount *= 100000
        elif unit.startswith("crore"):
            amount *= 10000000

        return amount

    except (ValueError, TypeError):
        return None


# =========================================================
# 15. CRITERION MATCHING CONFIGURATION
# =========================================================

INDIAN_STATES = [
    "andhra pradesh", "telangana", "karnataka", "tamil nadu",
    "kerala", "maharashtra", "gujarat", "rajasthan",
    "uttar pradesh", "madhya pradesh", "west bengal",
    "odisha", "bihar", "assam", "punjab", "haryana",
    "himachal pradesh", "uttarakhand", "jharkhand",
    "chhattisgarh", "goa", "sikkim", "tripura", "manipur",
    "meghalaya", "mizoram", "nagaland", "arunachal pradesh",
    "delhi", "jammu and kashmir", "ladakh", "puducherry"
]

CATEGORY_ALIASES = {
    "sc": [r"\bsc\b", r"scheduled castes?"],
    "st": [r"\bst\b", r"scheduled tribes?"],
    "obc": [r"\bobc\b", r"other backward class(?:es)?"],
    "ews": [r"\bews\b", r"economically weaker sections?"],
    "general": [
        r"general category",
        r"\bunreserved\b",
        r"\bgen\b"
    ]
}

YEAR_PATTERNS = {
    1: [r"\bfirst year\b", r"\b1st year\b", r"\byear 1\b"],
    2: [r"\bsecond year\b", r"\b2nd year\b", r"\byear 2\b"],
    3: [r"\bthird year\b", r"\b3rd year\b", r"\byear 3\b"],
    4: [r"\bfourth year\b", r"\b4th year\b", r"\byear 4\b"]
}

TECHNICAL_TERMS = [
    "engineering", "technology", "b.tech", "btech",
    "m.tech", "mtech", "diploma",
    "computer science", "information technology",
    "electronics", "mechanical", "civil",
    "electrical", "data science"
]


def criterion_result(
    criterion: str,
    status: str,
    explanation: str,
    evidence: str = ""
):
    return {
        "criterion": criterion,
        "status": status,
        "explanation": explanation,
        "evidence": evidence,
        "source_evidence": evidence
    }


def categories_in(text: str) -> set:
    """
    Recognise Indian scholarship categories, including
    common OCR variations.
    """
    text = normalize_text(text)

    # Repair common OCR joining errors.
    text = re.sub(r"sc\s*/\s*st\s*i\s*obc", "sc/st/obc", text)
    text = re.sub(r"sc\s*[/|]\s*st\s*[/|]\s*obc", "sc/st/obc", text)

    aliases = {
        "sc": [
            r"\bsc\b",
            r"scheduled\s+castes?"
        ],
        "st": [
            r"\bst\b",
            r"scheduled\s+tribes?"
        ],
        "obc": [
            r"\bobc\b",
            r"other\s+backward\s+classes?"
        ],
        "ews": [
            r"\bews\b",
            r"economically\s+weaker\s+sections?"
        ],
        "ebc": [
            r"\bebc\b",
            r"economically\s+backward\s+classes?"
        ],
        "minority": [
            r"\bminorities\b",
            r"\bminority\b"
        ],
        "general": [
            r"general\s+category",
            r"\bunreserved\b"
        ]
    }

    found = set()

    for category, patterns in aliases.items():
        if any(re.search(pattern, text) for pattern in patterns):
            found.add(category)

    return found


def years_in(text: str) -> set:
    found = set()

    for year, patterns in YEAR_PATTERNS.items():
        if any(re.search(pattern, text) for pattern in patterns):
            found.add(year)

    if not found:
        for number in re.findall(r"\b([1-4])\b", text):
            found.add(int(number))

    return found



# =========================================================
# 16. INDIVIDUAL MATCHING CHECKS
# =========================================================

def check_income(criterion, text, profile):
    if "income" not in text:
        return None

    income_limit = extract_income_limit(criterion)

    if income_limit is None:
        return (
            "Unverified",
            "The income limit could not be reliably identified."
        )

    try:
        raw_income = profile.get("annual_income")

        if raw_income is None or str(raw_income).strip() == "":
            raise ValueError("Missing income")

        income_value = float(
            str(raw_income).replace(",", "").replace("₹", "").strip()
        )

        if income_value < 0:
            raise ValueError("Invalid income")

    except (TypeError, ValueError):
        return (
            "Unverified",
            "Enter a valid annual family income."
        )

    if income_value <= income_limit:
        return (
            "Matched",
            f"Annual income is within the limit of ₹{income_limit:,.0f}."
        )

    return (
        "Not matched",
        f"Annual income exceeds the limit of ₹{income_limit:,.0f}."
    )


def check_domicile(criterion, text, profile):
    if not any(
        word in text
        for word in ["domicile", "resident of", "belongs to", "state of"]
    ):
        return None

    required_states = [
        state for state in INDIAN_STATES
        if re.search(r"\b" + re.escape(state) + r"\b", text)
    ]

    if len(required_states) != 1:
        return (
            "Unverified",
            "The required domicile state could not be identified."
        )

    required_state = required_states[0]
    student_state = normalize_text(profile.get("state", ""))

    if not student_state:
        return ("Unverified", "Student state is missing.")

    if normalize_text(required_state) in student_state:
        return (
            "Matched",
            f"Student state matches {required_state.title()}."
        )

    return (
        "Not matched",
        f"Notice requires domicile in {required_state.title()}."
    )


def check_gender(criterion, text, profile):
    gender_restrictions = [
        r"\bonly\s+girls?\b",
        r"\bgirls?\s+only\b",
        r"\bonly\s+female\b",
        r"\bfemale\s+students?\s+only\b",
        r"\bwomen\s+candidates?\s+only\b",
        r"\bmust\s+be\s+a\s+girl\b",
        r"\bmust\s+be\s+female\b",
        r"\bgirl\s+students?\s+are\s+eligible\b",
        r"\bfemale\s+students?\s+are\s+eligible\b",
        r"\bgirl\s+students?\b"
    ]

    if not any(re.search(pattern, text) for pattern in gender_restrictions):
        return None

    gender = normalize_text(profile.get("gender", ""))

    if not gender:
        return ("Unverified", "Gender information is missing.")

    if gender in ["female", "woman", "girl", "f"]:
        return (
            "Matched",
            "Student gender satisfies the girl/female student condition."
        )

    if gender in ["male", "man", "boy", "m"]:
        return (
            "Not matched",
            "This scholarship condition requires a girl/female student."
        )

    return ("Unverified", "Student gender could not be recognised.")


def check_aicte(criterion, text, profile):
    if "aicte" not in text:
        return None

    if re.search(
        r"(?:not required|not mandatory|does not require|without)\s+"
        r"(?:an?\s+)?aicte",
        text
    ):
        return None

    approved = profile_boolean(
        profile.get("institution_approved_by_aicte")
    )

    if approved is None:
        return ("Unverified", "AICTE approval status is missing.")

    if not approved:
        return (
            "Not matched",
            "Institution is not marked as AICTE-approved."
        )

    return (
        "Matched",
        "Institution is marked as AICTE-approved."
    )


def check_technical(criterion, text, profile):
    technical_phrases = [
        "technical course",
        "technical degree",
        "technical diploma",
        "engineering course",
        "technical programmes",
        "technical programs",
        "technical programme",
        "technical program",
        "technical/diploma",
        "technical or diploma"
    ]

    if not any(phrase in text for phrase in technical_phrases):
        return None

    course = normalize_text(profile.get("course", ""))

    if not course:
        return ("Unverified", "Course information is missing.")

    if any(term in course for term in TECHNICAL_TERMS):
        return ("Matched", "Course appears to be technical.")

    return (
        "Unverified",
        "Course does not clearly appear to be technical. "
        "Manual verification is recommended."
    )


def check_category(criterion, text, profile):
    required = categories_in(text)

    if not required:
        return None

    student_text = normalize_text(profile.get("category", ""))

    if not student_text:
        return ("Unverified", "Student category is missing.")

    student = categories_in(student_text)

    if not student:
        return ("Unverified", "Student category could not be recognised.")

    if len(required) > 1:
        return (
            "Unverified",
            "Multiple categories are mentioned. Manual interpretation is required."
        )

    if required == student:
        return (
            "Matched",
            "Student category matches the stated condition."
        )

    return (
        "Not matched",
        "Notice specifies "
        f"{'/'.join(sorted(c.upper() for c in required))} category."
    )


def check_study_year(criterion, text, profile):
    required = set()

    for year, patterns in YEAR_PATTERNS.items():
        if any(re.search(pattern, text) for pattern in patterns):
            required.add(year)

    # Explicit first-year wording, including common OCR variations.
    first_year_patterns = [
        r"\b1st\s+year\b",
        r"\bfirst\s+year\b",
        r"\b1st[- ]year\b",
        r"\bfirst[- ]year\b"
    ]

    if any(re.search(pattern, text) for pattern in first_year_patterns):
        required.add(1)

    if not required:
        return None

    student_text = normalize_text(profile.get("study_year", ""))

    if not student_text:
        return ("Unverified", "Study year is missing.")

    # A completed degree is not equivalent to current first-year admission.
    completed_terms = [
        "completed",
        "graduated",
        "degree completed",
        "course completed",
        "passed out"
    ]

    if any(term in student_text for term in completed_terms):
        if 1 in required:
            return (
                "Not matched",
                "The profile indicates that the degree is completed, "
                "but the notice requires admission to the first year."
            )

    student = years_in(student_text)

    if not student:
        return ("Unverified", "Study year could not be recognised.")

    if len(required) > 1:
        return (
            "Unverified",
            "Multiple study years are mentioned. Manual verification is required."
        )

    if required & student:
        return ("Matched", "Study year matches the stated condition.")

    return (
        "Not matched",
        "Notice specifies year "
        f"{', '.join(str(y) for y in sorted(required))}."
    )


def check_admission_route(criterion, text, profile):
    route_phrases = [
        "centralized admission",
        "centralised admission",
        "centralized admission process",
        "centralised admission process",
        "state government admission",
        "central government admission"
    ]

    if not any(phrase in text for phrase in route_phrases):
        return None

    # Prefer an explicit boolean profile field.
    route_value = None

    for key in [
        "admission_through_centralized_process",
        "centralized_admission",
        "centralised_admission"
    ]:
        if key in profile:
            route_value = profile_boolean(profile.get(key))
            if route_value is not None:
                break

    if route_value is True:
        return (
            "Matched",
            "Admission through the centralized process is confirmed in the profile."
        )

    if route_value is False:
        return (
            "Not matched",
            "The profile indicates admission was not through the required "
            "centralized admission process."
        )

    # Try a text-based admission route if the profile has one.
    admission_mode = normalize_text(
        profile.get("admission_mode")
        or profile.get("admission_route")
        or ""
    )

    if admission_mode:
        if any(term in admission_mode for term in [
            "centralized", "centralised", "state counselling",
            "state government counselling", "central government counselling"
        ]):
            return (
                "Matched",
                "The recorded admission route appears to satisfy the condition."
            )

        if any(term in admission_mode for term in [
            "management quota", "direct admission", "institution level"
        ]):
            return (
                "Not matched",
                "The recorded admission route does not indicate the required "
                "centralized admission process."
            )

    return (
        "Unverified",
        "Centralized admission status is not available in the student profile."
    )


def check_lateral_entry(criterion, text, profile):
    if "lateral entry" not in text:
        return None

    if "not eligible" in text or "not applicable" in text:
        return None

    lateral = profile_boolean(profile.get("lateral_entry"))

    if lateral is None:
        return ("Unverified", "Lateral-entry status is missing.")

    if not any(
        phrase in text
        for phrase in [
            "lateral entry students",
            "students admitted through lateral entry",
            "admitted through lateral entry",
            "lateral entry candidates"
        ]
    ):
        return (
            "Unverified",
            "Lateral entry is mentioned, but the condition is ambiguous."
        )

    if lateral:
        return (
            "Matched",
            "Student is marked as a lateral-entry applicant."
        )

    return (
        "Not matched",
        "Notice specifies lateral-entry students."
    )


def check_girls_per_family(criterion, text, profile):
    family_condition = (
        re.search(
            r"(?:maximum|max(?:imum)?\s+of|not\s+more\s+than|up\s+to)\s*"
            r"(?:two|2)\s+girls?",
            text
        )
        or re.search(
            r"\b(?:two|2)\s+girls?\s+(?:from|in|per)\s+(?:a\s+)?family\b",
            text
        )
        or re.search(
            r"\bmaximum\s+two\s+girl\s+children\b",
            text
        )
    )

    if not family_condition:
        return None

    # IMPORTANT: This must be the total number of girls in the family,
    # NOT the number of students applying for the scholarship.
    family_count_keys = [
        "number_of_girl_children_in_family",
        "number_of_girls_in_family",
        "total_girls_in_family",
        "girls_in_family",
        "number_of_daughters_in_family",
        "family_girl_count",
        "number_of_girl_children",
        "girls_in_household"
    ]

    count_value = None

    for key in family_count_keys:
        value = profile.get(key)

        if value is not None and str(value).strip() != "":
            count_value = value
            break

    if count_value is None:
        return (
            "Unverified",
            "The total number of girl children in the family is missing. "
            "The number of applicants cannot replace this information."
        )

    try:
        count = int(str(count_value).strip())

        if count < 1:
            raise ValueError("Invalid family count")

    except (TypeError, ValueError):
        return (
            "Unverified",
            "Enter a valid total number of girl children in the family."
        )

    if count <= 2:
        return (
            "Matched",
            f"There are {count} girl child(ren) in the family, "
            "within the maximum limit of two."
        )

    return (
        "Not matched",
        f"There are {count} girl children in the family, "
        "which exceeds the maximum limit of two."
    )


def check_disability(criterion, text, profile):
    disability_terms = [
        "differently abled",
        "differently-abled",
        "persons with disabilities",
        "person with disability",
        "disabled students",
        "disability"
    ]

    if not any(term in text for term in disability_terms):
        return None

    if any(
        phrase in text
        for phrase in [
            "not restricted to persons with disabilities",
            "disability is not required",
            "all students irrespective of disability"
        ]
    ):
        return None

    disability = profile_boolean(profile.get("differently_abled"))

    if disability is None:
        return (
            "Unverified",
            "Disability status is required to verify this condition."
        )

    if disability:
        return (
            "Matched",
            "Student disability status satisfies this condition."
        )

    return (
        "Unverified",
        "Disability is mentioned, but the notice's exact restriction "
        "requires manual verification."
    )


CRITERION_CHECKS = [
    check_income,
    check_domicile,
    check_gender,
    check_aicte,
    check_technical,
    check_category,
    check_study_year,
    check_admission_route,
    check_lateral_entry,
    check_girls_per_family,
    check_disability
]



# =========================================================
# 17. MATCH ONE CRITERION
# =========================================================

def match_single_criterion(
    criterion_item: Any,
    profile: dict
):
    if isinstance(criterion_item, str):
        criterion = criterion_item.strip()
        confidence = "low"
        verification_required = True
        evidence = ""

    elif isinstance(criterion_item, dict):
        criterion = str(
            criterion_item.get("criterion")
            or criterion_item.get("text")
            or criterion_item.get("requirement")
            or ""
        ).strip()

        confidence = normalize_text(
            criterion_item.get("confidence", "medium")
        )

        verification_required = (
            criterion_item.get("verification_required") is True
        )

        evidence = str(
            criterion_item.get("source_evidence")
            or criterion_item.get("evidence")
            or criterion_item.get("evidence_text")
            or ""
        ).strip()

    else:
        return criterion_result(
            "",
            "Unverified",
            "Invalid criterion format."
        )

    if not criterion:
        return criterion_result(
            "",
            "Unverified",
            "Criterion text is missing."
        )

    if not is_valid_eligibility_criterion(criterion):
        return None

    text = normalize_text(criterion)

   

    outcomes = []

    # -----------------------------------------------------
    # RUN ALL MATCHING CHECKS
    # -----------------------------------------------------

    for check in CRITERION_CHECKS:
        try:
            outcome = check(criterion, text, profile)

            print("CHECK FUNCTION:", check.__name__)
            print("CHECK RESULT:", outcome)

            logger.info(
                "CHECK: %s | RESULT: %s",
                check.__name__,
                outcome
            )

            if outcome is not None:
                outcomes.append(outcome)

        except Exception as error:
            print(
                "CHECK FAILED:",
                check.__name__,
                "| ERROR:",
                error
            )

            logger.exception(
                "CHECK FAILED: %s | ERROR: %s",
                check.__name__,
                error
            )

    # -----------------------------------------------------
    # HANDLE NO MATCHING RESULTS
    # -----------------------------------------------------

    if not outcomes:
        status = "Unverified"
        explanation = (
            "This condition requires manual review because "
            "the matching engine cannot safely verify it."
        )

        print("FINAL STATUS:", status)
        print("================================\n")

        return criterion_result(
            criterion,
            status,
            explanation,
            evidence
        )

    # -----------------------------------------------------
    # DETERMINE FINAL STATUS
    # -----------------------------------------------------

    not_matched = [
        item for item in outcomes
        if normalize_text(item[0]) == "not matched"
    ]

    unverified = [
        item for item in outcomes
        if normalize_text(item[0]) == "unverified"
    ]

    if not_matched:
        status = "Not Matched"
        chosen = not_matched

    elif unverified:
        status = "Unverified"
        chosen = unverified

    else:
        status = "Matched"
        chosen = outcomes

    # -----------------------------------------------------
    # BUILD EXPLANATION
    # -----------------------------------------------------

    explanation = " ".join(
        item[1] for item in chosen
    )

    if status != "Not Matched" and (
        confidence == "low" or verification_required
    ):
        explanation += (
            " Manual verification is required before "
            "making a final eligibility decision."
        )

        if status == "Matched":
            status = "Unverified"

    # -----------------------------------------------------
    # FINAL DEBUG OUTPUT
    # -----------------------------------------------------

    print("FINAL STATUS:", status)
    print("CRITERION:", criterion)
    print("================================\n")

    logger.info(
        "FINAL CRITERION RESULT: %s | %s",
        status,
        criterion
    )

    # -----------------------------------------------------
    # RETURN RESULT
    # -----------------------------------------------------

    return criterion_result(
        criterion,
        status,
        explanation,
        evidence
    )



# =========================================================
# 18. BUILD OVERALL ELIGIBILITY RESULT
# =========================================================

def build_eligibility_result(
    notification: dict,
    student_profile: dict
):
    criteria = safe_list(
        notification.get("eligibility_criteria")
    )

    results = []

    for item in criteria:
        try:
            matched_result = match_single_criterion(
                item,
                student_profile
            )

            if not isinstance(matched_result, dict):
                continue

            if isinstance(item, dict):
                fallback_criterion = (
                    item.get("criterion")
                    or item.get("text")
                    or item.get("requirement")
                    or ""
                )
            else:
                fallback_criterion = item

            criterion_text = str(
                matched_result.get("criterion")
                or fallback_criterion
                or ""
            ).strip()

            if not criterion_text:
                continue

            raw_status = normalize_text(
                matched_result.get("status", "Unverified")
            )

            status_aliases = {
                "matched": "Matched",
                "eligible": "Matched",
                "not matched": "Not matched",
                "not_matched": "Not matched",
                "unmatched": "Not matched",
                "not eligible": "Not matched",
                "unverified": "Unverified",
                "unknown": "Unverified"
            }

            status = status_aliases.get(
                raw_status,
                "Unverified"
            )

            explanation = str(
                matched_result.get("explanation")
                or matched_result.get("reason")
                or ""
            ).strip()

            if not explanation:
                explanation = (
                    "The condition requires additional verification."
                )

            evidence = str(
                matched_result.get("source_evidence")
                or matched_result.get("evidence")
                or ""
            ).strip()

            if isinstance(item, dict) and not evidence:
                evidence = str(
                    item.get("source_evidence")
                    or item.get("evidence")
                    or item.get("evidence_text")
                    or item.get("source_text")
                    or ""
                ).strip()

            if not evidence:
                evidence = (
                    "No separate source evidence was extracted. "
                    "Please verify this condition in the original notice."
                )

            results.append({
                "criterion": criterion_text,
                "status": status,
                "explanation": explanation,
                "evidence": evidence,
                "source_evidence": evidence
            })

        except Exception as error:
            logger.exception(
                "Criterion matching error: %s",
                error
            )

    matched = sum(
        item["status"] == "Matched"
        for item in results
    )

    unmatched = sum(
        item["status"] == "Not matched"
        for item in results
    )

    unverified = sum(
        item["status"] == "Unverified"
        for item in results
    )

    total = len(results)

    if total == 0:
        overall = "More information required"
    elif unmatched > 0:
        overall = "Not eligible based on matched criteria"
    elif unverified > 0:
        overall = "Potentially eligible"
    else:
        overall = "Eligible"

    return {
        "overall_status": overall,
        "total_criteria": total,
        "matched_criteria": matched,
        "unmatched_criteria": unmatched,
        "unverified_criteria": unverified,
        "criteria_results": results,
        "disclaimer": (
            "This is a preliminary automated comparison, "
            "not an official eligibility decision. "
            "Verify all conditions with the issuing authority."
        )
    }


# =========================================================
# 19. ELIGIBILITY MATCHING ENDPOINT
# =========================================================

@app.post("/match-eligibility")
async def match_eligibility(request: EligibilityMatchRequest):
    submitted_data = request.notification_analysis
    student_profile = request.student_profile

    print("\n========== RECEIVED STUDENT PROFILE ==========")
    print("STUDENT PROFILE:", student_profile)
    print("STUDY YEAR:", student_profile.get("study_year"))
    print("==============================================\n")

    if not isinstance(submitted_data, dict):
        raise HTTPException(
            status_code=400,
            detail="Invalid notification analysis."
        )

    if not isinstance(student_profile, dict):
        raise HTTPException(
            status_code=400,
            detail="Invalid student profile."
        )

    analysis = submitted_data.get("analysis", submitted_data)

    if not isinstance(analysis, dict):
        raise HTTPException(
            status_code=400,
            detail="Invalid analysis object."
        )

    def clean_name(value):
        value = str(value or "").lower().strip()
        value = re.sub(r"[^a-z0-9\s]", " ", value)
        return re.sub(r"\s+", " ", value).strip()

    def to_list(value):
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            return [value]
        return []

    def get_name(item):
        if isinstance(item, str):
            return item.strip()

        if isinstance(item, dict):
            return str(
                item.get("scheme_name")
                or item.get("name")
                or item.get("title")
                or ""
            ).strip()

        return ""

    def get_criteria(item):
        if isinstance(item, list):
            return item

        if not isinstance(item, dict):
            return []

        for key in (
            "eligibility_criteria",
            "criteria",
            "eligibility_requirements",
            "requirements",
            "eligibility"
        ):
            value = item.get(key)

            if isinstance(value, list):
                return value

            if isinstance(value, str) and value.strip():
                return [value.strip()]

        return []

    scheme_extraction = (
        submitted_data.get("scheme_wise_extraction")
        or analysis.get("scheme_wise_extraction")
        or {}
    )

    if isinstance(scheme_extraction, list):
        scheme_list = [
            item for item in scheme_extraction
            if isinstance(item, dict)
        ]

    elif isinstance(scheme_extraction, dict):
        scheme_list = [
            item for item in to_list(
                scheme_extraction.get("schemes")
            )
            if isinstance(item, dict)
        ]

        if not scheme_list:
            for key, value in scheme_extraction.items():
                if isinstance(value, dict):
                    entry = dict(value)
                    entry.setdefault("scheme_name", key)
                    scheme_list.append(entry)
    else:
        scheme_list = []

    detected_schemes = (
        submitted_data.get("detected_schemes")
        or analysis.get("detected_schemes")
        or []
    )

    detected_names = []

    for item in to_list(detected_schemes):
        name = get_name(item)

        if name and name not in detected_names:
            detected_names.append(name)

    if not detected_names:
        detected_names = [
            get_name(item)
            for item in scheme_list
            if get_name(item)
        ]

    source_analysis_mode = (
        submitted_data.get("analysis_mode")
        or analysis.get("analysis_mode")
        or request.analysis_mode
    )

    scheme_name = request.scheme_name

    # -----------------------------------------------------
    # SCHEME SELECTION
    # -----------------------------------------------------

    if not scheme_name and len(detected_names) == 1:
        scheme_name = detected_names[0]

    if not scheme_name and len(detected_names) > 1:
        available_schemes = []

        for name in detected_names:
            matching = next(
                (
                    item for item in scheme_list
                    if clean_name(get_name(item)) == clean_name(name)
                ),
                {}
            )

            available_schemes.append({
                "scheme_name": name,
                "criteria_count": len(get_criteria(matching))
            })

        return {
            "success": True,
            "matching_mode": "rule_based",
            "selected_scheme": None,
            "requires_scheme_selection": True,
            "available_schemes": available_schemes,
            "result": {
                "overall_status": "Select a scholarship",
                "total_criteria": 0,
                "matched_criteria": 0,
                "unmatched_criteria": 0,
                "unverified_criteria": 0,
                "criteria_results": [],
                "description": "",
                "disclaimer": "Select one scholarship before matching."
            },
            "message": "Please select a scholarship."
        }

    if not scheme_name:
        raise HTTPException(
            status_code=400,
            detail="No scholarship was selected or detected."
        )

    # -----------------------------------------------------
    # FIND SELECTED SCHEME
    # -----------------------------------------------------

    selected_scheme = None
    selected_normalized = clean_name(scheme_name)

    for item in scheme_list:
        if clean_name(get_name(item)) == selected_normalized:
            selected_scheme = item
            break

    if selected_scheme is None:
        possible_matches = []

        for item in scheme_list:
            extracted_name = clean_name(get_name(item))

            if not extracted_name:
                continue

            if (
                selected_normalized in extracted_name
                or extracted_name in selected_normalized
            ):
                possible_matches.append(item)

        if len(possible_matches) == 1:
            selected_scheme = possible_matches[0]

    # -----------------------------------------------------
    # GET CRITERIA
    # -----------------------------------------------------

    criteria = []

    if selected_scheme:
        criteria = get_criteria(selected_scheme)

    if not criteria and len(detected_names) <= 1:
        criteria = get_criteria(analysis)

    if not criteria:
        available = [
            {
                "scheme_name": get_name(item),
                "criteria_count": len(get_criteria(item))
            }
            for item in scheme_list
        ]

        logger.warning(
            "No criteria for selected scheme %s. "
            "Detected schemes: %s. Available schemes: %s",
            scheme_name,
            detected_names,
            available
        )

        raise HTTPException(
            status_code=422,
            detail={
                "message": (
                    "No eligibility criteria were extracted for "
                    "the selected scheme. Check scheme-wise extraction."
                ),
                "selected_scheme": scheme_name,
                "available_schemes": available,
                "detected_schemes": detected_names
            }
        )

    # -----------------------------------------------------
    # NORMALIZE CRITERIA
    # -----------------------------------------------------

    normalized_criteria = []

    for item in criteria:
        if isinstance(item, str):
            criterion_text = item.strip()

            if not criterion_text:
                continue

            normalized_criteria.append({
                "criterion": criterion_text,
                "explanation": criterion_text,
                "source_evidence": "",
                "confidence": "low",
                "verification_required": True
            })

        elif isinstance(item, dict):
            criterion_text = (
                item.get("criterion")
                or item.get("text")
                or item.get("requirement")
                or item.get("condition")
                or item.get("description")
                or ""
            )

            if not str(criterion_text).strip():
                continue

            evidence = (
                item.get("source_evidence")
                or item.get("evidence")
                or item.get("evidence_text")
                or item.get("source_text")
                or ""
            )

            confidence = normalize_text(
                item.get("confidence", "medium")
            )

            if confidence not in ["high", "medium", "low"]:
                confidence = "low"

            normalized_criteria.append({
                "criterion": str(criterion_text).strip(),
                "explanation": str(
                    item.get("explanation")
                    or item.get("reason")
                    or criterion_text
                ).strip(),
                "source_evidence": str(evidence).strip(),
                "confidence": confidence,
                "verification_required": (
                    item.get("verification_required") is True
                    or not str(evidence).strip()
                    or confidence == "low"
                )
            })

    if not normalized_criteria:
        raise HTTPException(
            status_code=422,
            detail="Extracted criteria could not be normalized."
        )

    # -----------------------------------------------------
    # DESCRIPTION
    # -----------------------------------------------------

    description = ""

    if selected_scheme:
        description = (
            selected_scheme.get("description")
            or selected_scheme.get("scheme_description")
            or ""
        )

    if not description:
        description = (
            analysis.get("description")
            or analysis.get("scheme_description")
            or ""
        )

    # -----------------------------------------------------
    # DEBUG WITHOUT PERSONAL PROFILE DATA
    # -----------------------------------------------------

    logger.info(
        "Eligibility matching started. Scheme: %s. Criteria: %s",
        scheme_name,
        len(normalized_criteria)
    )

    # -----------------------------------------------------
    # RUN MATCHING ENGINE
    # -----------------------------------------------------

    result = build_eligibility_result(
        {
            "eligibility_criteria": normalized_criteria
        },
        student_profile
    )

    # -----------------------------------------------------
    # RESTORE ORIGINAL EVIDENCE
    # -----------------------------------------------------

    original_criteria = {
        clean_name(item["criterion"]): item
        for item in normalized_criteria
    }

    for matched_item in result.get("criteria_results", []):
        key = clean_name(matched_item.get("criterion", ""))
        source_item = original_criteria.get(key, {})

        if not matched_item.get("explanation"):
            matched_item["explanation"] = source_item.get(
                "explanation",
                "Manual verification is required."
            )

        evidence = (
            source_item.get("source_evidence")
            or matched_item.get("source_evidence")
            or matched_item.get("evidence")
            or ""
        )

        matched_item["evidence"] = evidence
        matched_item["source_evidence"] = evidence

    # -----------------------------------------------------
    # FINAL RESULT
    # -----------------------------------------------------

    result["scheme_name"] = scheme_name
    result["description"] = description

    result["total_criteria"] = len(
        result.get("criteria_results", [])
    )

    logger.info(
        "Eligibility matching completed. Scheme: %s. "
        "Total criteria: %s. Overall status: %s",
        scheme_name,
        result["total_criteria"],
        result.get("overall_status")
    )

    return {
        "success": True,
        "matching_mode": "rule_based",
        "source_analysis_mode": source_analysis_mode,
        "selected_scheme": scheme_name,
        "requires_scheme_selection": False,
        "review_required": (
            result.get("overall_status") != "Eligible"
        ),
        "result": result,
        "message": (
            "Preliminary eligibility comparison completed. "
            "Verify all conditions against the original notification."
        )
    }


# =========================================================
# 20. RUN APPLICATION
# =========================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True
    )
