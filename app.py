
import streamlit as st
import requests
import hashlib

# =====================================================
# 1. PAGE CONFIGURATION
# =====================================================

st.set_page_config(
    page_title="NOTICE2ACTION AI",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed"
)

API_URL = "http://127.0.0.1:8000"


# =====================================================
# 2. SESSION STATE
# =====================================================

defaults = {
    "extracted_text": "",
    "upload_info": None,
    "analysis": None,
    "analysis_mode": None,
    "detected_schemes": [],
    "analysis_message": "",
    "student_profile": None,
    "eligibility_result": None,
    "current_page": "Home",
    "selected_file_hash": None
}

for key, value in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = value


# =====================================================
# 3. CUSTOM DESIGN
# =====================================================

st.markdown("""
<style>
:root {
    --n2a-blue: #2563EB;
    --n2a-blue-dark: #1D4ED8;
    --n2a-ink: #F8FAFC;
    --n2a-muted: #CBD5E1;
    --n2a-border: #3B4B63;
    --n2a-soft: #1E293B;
}
.stApp {
    background: linear-gradient(135deg, #0B1220 0%, #142238 52%, #182B40 100%) fixed !important;
    color: #F8FAFC !important;
}
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
[data-testid="stMainBlockContainer"] {
    background: transparent !important;
}
[data-testid="stHeader"] {
    background: rgba(11, 18, 32, 0.96);
}
.stMainBlockContainer, .block-container {
    max-width: 1240px !important;
    width: calc(100% - 3rem) !important;
    padding: 1.7rem 1.5rem 3rem !important;
    margin: 0 auto !important;
}
h1, h2, h3, h4 {
    color: var(--n2a-ink) !important;
    letter-spacing: -0.025em;
}
h1 { font-size: clamp(2rem, 4vw, 3rem) !important; font-weight: 850 !important; }
h2 { font-size: clamp(1.45rem, 3vw, 2rem) !important; font-weight: 780 !important; }
h3 { font-size: 1.2rem !important; font-weight: 720 !important; }
p, li, label, [data-testid="stMarkdownContainer"] {
    line-height: 1.65;
}
[data-testid="stRadio"] > label { font-weight: 700; color: var(--n2a-ink); }
.stButton button, .stFormSubmitButton button {
    border-radius: 12px !important;
    border: 1px solid #2563EB !important;
    background: linear-gradient(135deg, #2563EB, #1D4ED8) !important;
    color: #FFFFFF !important;
    font-weight: 700 !important;
    min-height: 46px;
    padding: 0.65rem 1.2rem !important;
    box-shadow: 0 5px 14px rgba(37, 99, 235, 0.16);
    transition: transform .15s ease, box-shadow .15s ease;
}
.stButton button:hover, .stFormSubmitButton button:hover {
    transform: translateY(-1px);
    box-shadow: 0 8px 20px rgba(37, 99, 235, 0.22);
}
[data-testid="stMetric"] {
    background: #1E2D43;
    border: 1px solid var(--n2a-border);
    border-radius: 16px;
    padding: 16px 18px;
    box-shadow: 0 4px 16px rgba(15, 23, 42, 0.045);
}
[data-testid="stMetricLabel"] { color: var(--n2a-muted) !important; font-weight: 650; }
[data-testid="stMetricValue"] { color: var(--n2a-blue-dark) !important; font-weight: 800; }
[data-testid="stFileUploader"] {
    background: #1B2A40;
    border: 1.5px dashed #6EA8E8;
    border-radius: 16px;
    padding: 12px;
}
.stTextInput input, .stTextArea textarea, .stNumberInput input,
.stSelectbox div[data-baseweb="select"] > div {
    border-radius: 10px !important;
}
[data-testid="stExpander"] {
    border: 1px solid var(--n2a-border);
    border-radius: 13px;
    background: #1E2D43;
    overflow: hidden;
}
[data-testid="stAlert"] { border-radius: 12px; }
hr { border-color: #E2E8F0 !important; margin: 1.4rem 0 !important; }
.n2a-hero {
    background: linear-gradient(120deg, #1E2D43 0%, #263B55 100%);
    border: 1px solid #405675;
    border-radius: 22px;
    padding: clamp(22px, 4vw, 38px);
    margin: 8px 0 22px;
    box-shadow: 0 10px 30px rgba(37, 99, 235, .07);
}
.n2a-eyebrow {
    color: #93C5FD; font-size: .78rem; font-weight: 800;
    letter-spacing: .12em; text-transform: uppercase; margin-bottom: 10px;
}
.n2a-hero-title {
    color: #FFFFFF; font-size: clamp(1.8rem, 4vw, 2.65rem);
    line-height: 1.12; font-weight: 850; letter-spacing: -.04em;
}
.n2a-hero-copy { color: #475569; font-size: 1.02rem; max-width: 760px; margin-top: 12px; }
.n2a-pill {
    display: inline-block; padding: 6px 11px; border-radius: 999px;
    color: #DBEAFE; background: #304B70; font-size: .78rem; font-weight: 750;
    margin: 0 6px 6px 0;
}
.n2a-feature {
    background: #1E2D43; border: 1px solid #405675; border-radius: 15px;
    padding: 17px; min-height: 112px; box-shadow: 0 4px 15px rgba(15,23,42,.035);
}
.n2a-feature-icon { font-size: 1.35rem; margin-bottom: 6px; }
.n2a-feature-title { color: #0F172A; font-weight: 750; margin-bottom: 3px; }
.n2a-feature-copy { color: #64748B; font-size: .88rem; line-height: 1.45; }
.n2a-footer {
    text-align: center; padding: 22px 10px; margin-top: 26px;
    color: #CBD5E1; border-top: 1px solid #405675;
}
@media (max-width: 768px) {
    .stMainBlockContainer, .block-container {
        width: 100% !important; padding: 1rem 1rem 2rem !important;
    }
    h1 { font-size: 2rem !important; }
    [data-testid="stMetric"] { padding: 12px; }
    .n2a-hero { border-radius: 16px; }
    .stButton button, .stFormSubmitButton button { width: 100%; }
}

/* Dark theme readability overrides */
.stApp, [data-testid="stApp"], [data-testid="stAppViewContainer"],
[data-testid="stMain"], [data-testid="stMainBlockContainer"] {
    background-color: transparent !important;
    color: #F8FAFC !important;
}
.stApp p, .stApp li, .stApp label, .stApp span,
.stApp [data-testid="stMarkdownContainer"],
.stApp [data-testid="stWidgetLabel"] p,
.stApp [data-testid="stRadio"] label,
.stApp [data-testid="stCaptionContainer"] {
    color: #E2E8F0;
}
h1, h2, h3, h4, h5, h6,
.stApp [data-testid="stMarkdownContainer"] strong {
    color: #FFFFFF !important;
}
[data-testid="stMetric"], [data-testid="stExpander"],
[data-testid="stFileUploader"], [data-testid="stForm"],
[data-testid="stVerticalBlockBorderWrapper"] {
    background-color: #1E2D43 !important;
    border-color: #405675 !important;
}
[data-testid="stMetricLabel"] { color: #CBD5E1 !important; }
[data-testid="stMetricValue"] { color: #93C5FD !important; }
.stTextInput input, .stTextArea textarea, .stNumberInput input,
[data-baseweb="select"] > div {
    background-color: #263B55 !important;
    color: #FFFFFF !important;
    border-color: #526B8B !important;
}
.stTextInput input::placeholder, .stTextArea textarea::placeholder {
    color: #B7C5D8 !important;
}
[data-testid="stFileUploader"] section,
[data-testid="stFileUploader"] small {
    color: #E2E8F0 !important;
}
hr { border-color: #405675 !important; }


/* High-contrast text fixes for all custom dashboard cards */
.n2a-hero-copy {
    color: #E2EAF5 !important;
}
.n2a-feature-title {
    color: #FFFFFF !important;
}
.n2a-feature-copy {
    color: #D1DCEB !important;
}
.n2a-feature {
    background: #223650 !important;
    border-color: #526B8B !important;
}
.n2a-hero {
    background: linear-gradient(120deg, #1C2E46 0%, #263F5D 100%) !important;
    border-color: #526B8B !important;
}
.n2a-pill {
    color: #FFFFFF !important;
    background: #315783 !important;
}
.n2a-footer {
    color: #D1DCEB !important;
}

</style>
""", unsafe_allow_html=True)


# =====================================================
# 4. HEADER
# =====================================================

st.markdown("""
<div class="n2a-hero">
  <div class="n2a-eyebrow">AI-powered scholarship assistant</div>
  <div class="n2a-hero-title">NOTICE2ACTION AI</div>
  <div class="n2a-hero-copy">
    Turn confusing scholarship and government notifications into clear,
    personalized next steps. Upload a notice, understand its key details,
    and check your eligibility against the extracted criteria.
  </div>
  <div style="margin-top:17px">
    <span class="n2a-pill">PDF intelligence</span>
    <span class="n2a-pill">Gemini-powered analysis</span>
    <span class="n2a-pill">Eligibility assistance</span>
  </div>
</div>
""", unsafe_allow_html=True)


# =====================================================
# 5. NAVIGATION
# =====================================================

page = st.radio(
    "Navigation",
    ["Home", "Student Profile"],
    horizontal=True,
    label_visibility="collapsed",
    key="current_page"
)

st.divider()



# =====================================================
# 6. STUDENT PROFILE PAGE
# =====================================================

if page == "Student Profile":

    st.header("🎓 Student Profile")

    st.write(
        "Create your student profile to receive personalized "
        "guidance based on your education and eligibility conditions."
    )

    st.info(
        "Your information is currently stored only during "
        "this Streamlit session."
    )

    existing = st.session_state.student_profile or {}

    education_options = [
        "Select education level", "10th", "Intermediate",
        "Undergraduate", "Postgraduate", "PhD", "Other"
    ]

    year_options = [
        "Select year", "1st Year", "2nd Year", "3rd Year",
        "4th Year", "Completed", "Not applicable"
    ]

    state_options = [
        "Select state", "Andhra Pradesh", "Arunachal Pradesh",
        "Assam", "Bihar", "Chhattisgarh", "Goa", "Gujarat",
        "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka",
        "Kerala", "Madhya Pradesh", "Maharashtra", "Manipur",
        "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Punjab",
        "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
        "Tripura", "Uttar Pradesh", "Uttarakhand",
        "West Bengal", "Delhi", "Other"
    ]

    category_options = [
        "Prefer not to say", "General", "OBC",
        "SC", "ST", "EWS", "Other"
    ]

    gender_options = [
        "Not provided", "Female", "Male", "Other"
    ]

    aicte_options = ["Not sure", "Yes", "No"]
    lateral_options = ["Not sure", "Yes", "No"]

    def selected_index(options, value):
        return options.index(value) if value in options else 0

    # ---------------------------------------------
    # PROFILE FORM
    # ---------------------------------------------

    with st.form("student_profile_form"):

        st.subheader("📚 Education Details")

        education_level = st.selectbox(
            "Current education level",
            education_options,
            index=selected_index(
                education_options,
                existing.get("education_level")
            )
        )

        course = st.text_input(
            "Course / Stream",
            value=existing.get("course", ""),
            placeholder="Example: B.Tech Computer Science"
        )

        study_year = st.selectbox(
            "Current year of study",
            year_options,
            index=selected_index(
                year_options,
                existing.get("study_year")
            )
        )

        st.divider()
        st.subheader("📍 Location")

        state = st.selectbox(
            "State / Union Territory",
            state_options,
            index=selected_index(
                state_options,
                existing.get("state")
            )
        )

        st.divider()
        st.subheader("📋 Additional Details")

        category = st.selectbox(
            "Category (optional)",
            category_options,
            index=selected_index(
                category_options,
                existing.get("category") or "Prefer not to say"
            )
        )

        annual_income = st.number_input(
            "Family annual income in ₹ (optional)",
            min_value=0,
            max_value=100000000,
            value=int(existing.get("annual_income") or 0),
            step=10000,
            help="Enter 0 if you prefer not to provide this information."
        )

        st.divider()
        st.subheader("🎯 Scholarship Eligibility Details")

        gender = st.selectbox(
            "Gender",
            gender_options,
            index=selected_index(
                gender_options,
                existing.get("gender") or "Not provided"
            )
        )

        aicte_default = existing.get("institution_approved_by_aicte")
        aicte_value = (
            "Yes" if aicte_default is True
            else "No" if aicte_default is False
            else "Not sure"
        )

        aicte_approved = st.selectbox(
            "Is your institution AICTE-approved?",
            aicte_options,
            index=selected_index(aicte_options, aicte_value)
        )

        lateral_default = existing.get("lateral_entry")
        lateral_value = (
            "Yes" if lateral_default is True
            else "No" if lateral_default is False
            else "Not sure"
        )

        lateral_entry = st.selectbox(
            "Did you enter through lateral entry?",
            lateral_options,
            index=selected_index(lateral_options, lateral_value)
        )

        number_of_girl_children = st.number_input(
            "Number of girl children in your family",
            min_value=0,
            max_value=10,
            value=int(
                existing.get("number_of_girl_children_in_family") or 0
            ),
            step=1
        )
        number_of_girl_students_applying = st.number_input(
            "How many girl students in your family are applying for this scholarship?",
            min_value=0,
            max_value=10,
            value=int(
                existing.get(
                    "number_of_girl_students_applying_from_family"
                ) or 0
            ),
            step=1,
            help="Enter the total number of girl students from your family applying for this scholarship. Enter 0 if unknown."
        )

        st.caption(
            "Unknown information will not be treated as a confirmed match."
        )

        submitted = st.form_submit_button(
            "💾 Save Student Profile",
            use_container_width=True
        )

        # -----------------------------------------
        # SAVE PROFILE
        # -----------------------------------------

        if submitted:
            
            if education_level == "Select education level":
                st.error("Please select your education level.")

            elif not course.strip():
                st.error("Please enter your course or stream.")

            elif study_year == "Select year":
                st.error("Please select your current study year.")

            elif state == "Select state":
                st.error("Please select your state.")

            else:

                st.session_state.student_profile = {
                    "education_level": education_level,
                    "course": course.strip(),
                    "study_year": study_year,
                    "state": state,

                    "category": (
                        None if category == "Prefer not to say"
                        else category
                    ),

                    "annual_income": (
                        annual_income if annual_income > 0
                        else None
                    ),

                    "gender": (
                        None if gender == "Not provided"
                        else gender
                    ),

                    "institution_approved_by_aicte": (
                        True if aicte_approved == "Yes"
                        else False if aicte_approved == "No"
                        else None
                    ),

                    "lateral_entry": (
                        True if lateral_entry == "Yes"
                        else False if lateral_entry == "No"
                        else None
                    ),

                    # Number of girls applying for the scholarship
                    "number_of_girl_students_applying_from_family": (
                        number_of_girl_students_applying
                        if number_of_girl_students_applying > 0
                        else None
                    ),

                    # Total number of girl children in the family
                    "number_of_girl_children_in_family": (
                        number_of_girl_children
                        if number_of_girl_children > 0
                        else None
                    )
                }
                
                
                st.session_state.eligibility_result = None

                st.success("✅ Student profile saved successfully!")

    # ---------------------------------------------
    # DISPLAY SAVED PROFILE
    # ---------------------------------------------

    profile = st.session_state.student_profile

    if profile:

        st.divider()
        st.subheader("✅ Your Saved Profile")

        col1, col2 = st.columns(2)

        with col1:
            st.write("**Education:**", profile.get("education_level"))
            st.write("**Course:**", profile.get("course"))
            st.write("**Study Year:**", profile.get("study_year"))
            st.write("**State:**", profile.get("state"))
            st.write(
                "**Category:**",
                profile.get("category") or "Not provided"
            )

        with col2:
            income = profile.get("annual_income")

            st.write(
                "**Family Annual Income:**",
                f"₹{income:,}" if income is not None else "Not provided"
            )

            st.write(
                "**Gender:**",
                profile.get("gender") or "Not provided"
            )

            aicte = profile.get("institution_approved_by_aicte")
            st.write(
                "**AICTE Approved:**",
                "Yes" if aicte is True
                else "No" if aicte is False
                else "Not provided"
            )

            lateral = profile.get("lateral_entry")
            st.write(
                "**Lateral Entry:**",
                "Yes" if lateral is True
                else "No" if lateral is False
                else "Not provided"
            )

            st.write(
                "**Girl Children in Family:**",
                profile.get("number_of_girl_children_in_family", 0)
            )

            applying_count = profile.get(
                "number_of_girl_students_applying_from_family"
            )
            st.write(
                "**Girl Students Applying from Family:**",
                applying_count if applying_count is not None else "Not provided"
            )

        st.success("Your profile is ready for eligibility matching.")

    st.divider()
    st.caption("NOTICE2ACTION AI | Team DevHarbour")


# =====================================================
# 7. HOME PAGE
# =====================================================

else:

    st.markdown("""
    <div class="n2a-feature">
      <div class="n2a-feature-title">Your personal notification workspace</div>
      <div class="n2a-feature-copy">
        Start by uploading an official scholarship, employment or government
        notification. NOTICE2ACTION AI will extract the information and organize
        the important details into an action plan.
      </div>
    </div>
    """, unsafe_allow_html=True)

    st.write("")

    feature_cols = st.columns(3)

    feature_items = [
        ("📄", "Understand notices", "Extract key information from PDF notifications."),
        ("✨", "AI analysis", "Identify schemes, dates, documents and action steps."),
        ("🎯", "Check eligibility", "Compare scheme criteria with your saved profile.")
    ]

    for feature_col, feature_item in zip(feature_cols, feature_items):
        with feature_col:
            st.markdown(
                f'<div class="n2a-feature"><div class="n2a-feature-icon">{feature_item[0]}</div>'
                f'<div class="n2a-feature-title">{feature_item[1]}</div>'
                f'<div class="n2a-feature-copy">{feature_item[2]}</div></div>',
                unsafe_allow_html=True
            )

    # =================================================
    # STUDENT PROFILE STATUS
    # =================================================

    profile = st.session_state.student_profile

    st.divider()

    st.subheader("🎓 Student Profile Status")

    if profile:

        st.success(
            f"Profile available: {profile['education_level']} | "
            f"{profile['course']} | {profile['state']}"
        )

        st.caption(
            "Your saved profile will be used for eligibility matching."
        )

    else:

        st.warning(
            "Student profile not created yet. "
            "Open Student Profile above to add your details."
        )

    # =================================================
    # 8. PDF UPLOAD
    # =================================================

    st.divider()

    st.subheader("1. Upload Notification")

    uploaded_file = st.file_uploader(
        "Choose your notification PDF",
        type=["pdf"],
        help="Upload a scholarship, employment or government notification."
    )

    if uploaded_file is not None:

        uploaded_bytes = uploaded_file.getvalue()
        current_file_hash = hashlib.sha256(uploaded_bytes).hexdigest()

        # Prevent results from a previously uploaded PDF from appearing
        # under a newly selected document.
        if st.session_state.selected_file_hash != current_file_hash:
            st.session_state.selected_file_hash = current_file_hash
            st.session_state.extracted_text = ""
            st.session_state.upload_info = None
            st.session_state.analysis = None
            st.session_state.analysis_mode = None
            st.session_state.detected_schemes = []
            st.session_state.analysis_message = ""
            st.session_state.eligibility_result = None

        st.info(f"📄 Selected file: {uploaded_file.name}")

        if st.button(
            "📤 Extract Document Information",
            use_container_width=True
        ):

            with st.spinner("Reading your notification..."):

                try:

                    files = {
                        "file": (
                            uploaded_file.name,
                            uploaded_bytes,
                            "application/pdf"
                        )
                    }

                    response = requests.post(
                        f"{API_URL}/upload-notification",
                        files=files,
                        timeout=120
                    )

                    if response.ok:

                        data = response.json()

                        extracted_text = data.get(
                            "extracted_text", ""
                        )

                        st.session_state.extracted_text = extracted_text
                        st.session_state.upload_info = data

                        # Clear previous analysis
                        st.session_state.analysis = None
                        st.session_state.analysis_mode = None
                        st.session_state.detected_schemes = []
                        st.session_state.analysis_message = ""
                        st.session_state.eligibility_result = None

                        if extracted_text.strip():

                            st.success(
                                "✅ Document extracted successfully!"
                            )

                            st.info(
                                f"Extracted {len(extracted_text):,} characters."
                            )

                        else:

                            st.error(
                                "The document was uploaded, but no text was extracted."
                            )

                    else:

                        st.error(
                            f"Extraction failed: {response.text}"
                        )

                except requests.RequestException as error:

                    st.error(f"Connection error: {error}")

    
    # =================================================
    # 9. EXTRACTION RESULTS
    # =================================================

    if st.session_state.upload_info:

        info = st.session_state.upload_info

        st.divider()
        st.subheader("2. Extraction Results")

        col1, col2 = st.columns(2)

        with col1:
            st.metric(
                "Total Pages",
                info.get("total_pages", "N/A")
            )

        with col2:
            st.metric(
                "OCR Used",
                "Yes" if info.get("ocr_used") else "No"
            )

        if "ocr_pages" in info:
            st.write(
                "**OCR Pages:**",
                info.get("ocr_pages", [])
            )

        if "unreadable_pages" in info:
            st.write(
                "**Unreadable Pages:**",
                info.get("unreadable_pages", [])
            )

        with st.expander("📖 View Extracted Text"):

            extracted = st.session_state.extracted_text

            st.write("### Extraction Debug Information")
            st.write("Character count:", len(extracted))
            st.write("Word count:", len(extracted.split()))

            st.write("First 2000 characters:")
            st.code(extracted[:2000])

            st.write("Last 1000 characters:")
            st.code(extracted[-1000:])

            if extracted.strip().lower() == "string":
                st.error("Only placeholder text was extracted!")

            elif len(extracted.strip()) < 100:
                st.warning("Very little text was extracted.")

            else:
                st.success(
                    "Actual document text appears to be available."
                )

    
# =================================================
# 10. NOTIFICATION ANALYSIS
# =================================================

if st.session_state.extracted_text:

    st.divider()

    st.subheader("3. Understand Your Notification")

    if st.button(
        "✨ Analyze My Notification",
        use_container_width=True
    ):

        extracted_text = (
            st.session_state.extracted_text.strip()
        )

        if not extracted_text:

            st.error("No extracted notification text found.")

        else:

            # Reset old analysis
            st.session_state.analysis = None
            st.session_state.analysis_mode = None
            st.session_state.detected_schemes = []
            st.session_state.analysis_message = ""
            st.session_state.eligibility_result = None

            st.info(
                f"Sending {len(extracted_text):,} characters to Gemini."
            )

            with st.spinner(
                "Analyzing notification. Please wait..."
            ):

                try:

                    payload = {
                        "extracted_text": extracted_text
                    }

                    response = requests.post(
                        f"{API_URL}/analyze-notification",
                        json=payload,
                        timeout=180
                    )

                    if response.ok:

                        analysis_response = response.json()

                        # -----------------------------------------
                        # PRESERVE MAIN AI ANALYSIS
                        # -----------------------------------------

                        analysis_data = analysis_response.get(
                            "analysis",
                            {}
                        )

                        if not isinstance(analysis_data, dict):
                            analysis_data = {}

                        # -----------------------------------------
                        # PRESERVE SCHEME-WISE EXTRACTION
                        # -----------------------------------------

                        scheme_extraction = analysis_response.get(
                            "scheme_wise_extraction",
                            analysis_data.get(
                                "scheme_wise_extraction",
                                {}
                            )
                        )

                        analysis_data["scheme_wise_extraction"] = (
                            scheme_extraction
                        )

                        # -----------------------------------------
                        # PRESERVE DETECTED SCHEMES
                        # -----------------------------------------

                        detected_schemes = analysis_response.get(
                            "detected_schemes",
                            []
                        )

                        analysis_data["detected_schemes"] = (
                            detected_schemes
                        )

                        # -----------------------------------------
                        # SAVE COMPLETE ANALYSIS
                        # -----------------------------------------

                        st.session_state.analysis = analysis_data

                        st.session_state.analysis_mode = (
                            analysis_response.get(
                                "analysis_mode",
                                "unknown"
                            )
                        )

                        st.session_state.detected_schemes = (
                            detected_schemes
                        )

                        st.session_state.analysis_message = (
                            analysis_response.get(
                                "message",
                                ""
                            )
                        )

                        st.success("✅ Analysis completed!")

                        # -----------------------------------------
                        # ANALYSIS INFORMATION
                        # -----------------------------------------

                        st.write(
                            "**Analysis Mode:**",
                            st.session_state.analysis_mode
                        )

                        st.write(
                            "**Extracted Text Length:**",
                            f"{len(extracted_text):,} characters"
                        )

                        st.write(
                            "**Detected Schemes:**",
                            len(st.session_state.detected_schemes)
                        )

                        # -----------------------------------------
                        # DEBUG INFORMATION
                        # -----------------------------------------

                        st.divider()

                        st.subheader(
                            "🔧 Analysis Debug Information"
                        )

                        st.write(
                            "Analysis Keys:",
                            list(analysis_data.keys())
                        )

                        st.write(
                            "Scheme-wise Extraction:"
                        )

                        st.json(scheme_extraction)

                        # -----------------------------------------
                        # DISPLAY DETECTED SCHEMES
                        # -----------------------------------------

                        if st.session_state.analysis_message:

                            st.info(
                                st.session_state.analysis_message
                            )

                        with st.expander(
                            "🔍 View Detected Schemes"
                        ):

                            st.json(
                                st.session_state.detected_schemes
                            )

                        # -----------------------------------------
                        # VALIDATE ANALYSIS
                        # -----------------------------------------

                        if (
                            not st.session_state.detected_schemes
                            and
                            st.session_state.analysis.get(
                                "notification_type"
                            ) == "Unspecified / Invalid Input"
                        ):

                            st.error(
                                "Gemini did not identify usable "
                                "notification content. "
                                "We need to inspect the backend "
                                "input and prompt."
                            )

                    else:

                        st.error(
                            f"Analysis failed: {response.text}"
                        )

                except requests.RequestException as error:

                    st.error(
                        f"Connection error: {error}"
                    )

                except (ValueError, TypeError) as error:

                    st.error(
                        f"Invalid analysis response: {error}"
                    )


    # =================================================
    # 11. DISPLAY NOTIFICATION ACTION PLAN
    # =================================================

    if st.session_state.analysis:

        result = st.session_state.analysis
        mode = st.session_state.analysis_mode

        st.divider()

        st.header("4. Your Notification Action Plan")

        # ANALYSIS MODE

        if  mode in ["gemini", "gemini_ai"]:

            st.success("🤖 AI-powered analysis")

        elif mode == "rule_based_fallback":

            st.warning(
                "⚠️ Basic extraction mode: Gemini unavailable. "
                "Information requires manual verification."
            )

        # BASIC INFORMATION

        st.subheader("📌 Basic Information")

        st.write(
            "**Notification Type:**",
            result.get("notification_type", "Not specified")
        )

        st.write(
            "**Scholarship / Scheme:**",
            result.get("scholarship_name", "Not specified")
        )

        st.write(
            "**Purpose:**",
            result.get("purpose", "Not specified")
        )

        # DETECTED SCHEMES

        detected_schemes = st.session_state.detected_schemes

        if detected_schemes:

            st.divider()

            st.subheader("🏛️ Detected Scholarship Schemes")

            for scheme in detected_schemes:

                if isinstance(scheme, dict):

                    st.markdown(
                        f"**{scheme.get('scheme_name', 'Unnamed scheme')}**"
                    )

                    st.caption(
                        f"Confidence: {scheme.get('confidence', 'Unknown')} "
                        f"| Verification required: "
                        f"{scheme.get('verification_required', 'Unknown')}"
                    )

                else:

                    st.write(scheme)

        # ELIGIBILITY CRITERIA

        st.divider()

        st.subheader("🎯 Eligibility Criteria")

        eligibility = result.get(
            "eligibility_criteria", []
        )

        if isinstance(eligibility, list):

            if eligibility:

                for item in eligibility:
                    st.markdown(f"- {item}")

            else:

                st.info(
                    "Eligibility details could not be reliably extracted. "
                    "Scheme-specific criteria need verification."
                )

        else:

            st.write(eligibility)

        # REQUIRED DOCUMENTS

        st.divider()

        st.subheader("📂 Required Documents")

        documents = result.get(
            "required_documents", []
        )

        if isinstance(documents, list):

            if documents:

                for item in documents:
                    st.markdown(f"📎 {item}")

            else:

                st.info(
                    "Required documents could not be reliably extracted."
                )

        else:

            st.write(documents)

        # IMPORTANT DATES

        st.divider()

        st.subheader("📅 Important Dates")

        dates = result.get(
            "important_dates", []
        )

        if isinstance(dates, list):

            if dates:

                for item in dates:

                    if isinstance(item, dict):

                        st.markdown(
                            f"**📅 {item.get('event', 'Event')}**"
                        )

                        st.write(
                            f"Date: {item.get('date', 'Not specified')}"
                        )

                        st.caption(
                            f"Status: {item.get('status', 'Unverified')} "
                            f"| Evidence: "
                            f"{item.get('evidence', 'Not provided')}"
                        )

                    else:

                        st.write(item)

            else:

                st.info(
                    "No reliable dates could be extracted."
                )

        else:

            st.write(dates)

        # ACTION CHECKLIST

        st.divider()

        st.subheader("✅ Your Action Checklist")

        actions = result.get(
            "action_steps", []
        )

        if isinstance(actions, list):

            if actions:

                for index, item in enumerate(actions):

                    checklist_file_id = (
                        st.session_state.selected_file_hash or "document"
                    )[:12]

                    st.checkbox(
                        str(item),
                        key=f"action_{checklist_file_id}_{index}"
                    )

            else:

                st.info(
                    "No action steps were generated."
                )

        else:

            st.write(actions)

        # INFORMATION TO VERIFY

        missing = result.get(
            "missing_information", []
        )

        if missing:

            st.divider()

            st.subheader("⚠️ Information to Verify")

            if isinstance(missing, list):

                for item in missing:
                    st.warning(str(item))

            else:

                st.warning(str(missing))

        # DISCLAIMER

        disclaimer = result.get("disclaimer")

        if disclaimer:
            st.info(disclaimer)

        st.caption(
            "Always verify eligibility and deadlines against "
            "the original official notification and issuing authority."
        )

        
        # =================================================
        # 12. SMART ELIGIBILITY MATCHING
        # =================================================

        st.divider()
        st.header("5. Smart Eligibility Matching")

        profile = st.session_state.student_profile

        # Get scheme-wise extraction from Gemini analysis
        scheme_extraction = result.get("scheme_wise_extraction", {})

        if isinstance(scheme_extraction, dict):
            scheme_list = scheme_extraction.get("schemes", [])
        elif isinstance(scheme_extraction, list):
            scheme_list = scheme_extraction
        else:
            scheme_list = []

        # Fallback to detected schemes
        if not scheme_list:
            scheme_list = st.session_state.detected_schemes or []

        # Normalize scheme names
        available_schemes = []

        for scheme in scheme_list:
            if isinstance(scheme, dict):
                name = (
                    scheme.get("scheme_name")
                    or scheme.get("name")
                    or scheme.get("title")
                )
            else:
                name = str(scheme)

            if name and name.strip() and name not in available_schemes:
                available_schemes.append(name.strip())

        # Final fallback to the main scholarship name
        if not available_schemes:
            fallback_name = result.get("scholarship_name")
            if fallback_name and fallback_name != "Not specified":
                available_schemes.append(fallback_name)

        if not profile:
            st.warning(
                "Please create and save your Student Profile "
                "before checking eligibility."
            )

        elif not available_schemes:
            st.warning(
                "No scholarship schemes were detected. "
                "Please check the notification analysis."
            )

        else:
            st.success(
                f"Student profile ready: {profile['education_level']} | "
                f"{profile['course']} | {profile['state']}"
            )

            st.subheader("Select a Scholarship")

            selected_scheme = st.selectbox(
                "Choose the scholarship you want to check",
                options=available_schemes,
                key="selected_scholarship"
            )

            st.caption(
                f"{len(available_schemes)} scholarship scheme(s) available."
            )

            if st.button(
                "🎯 Check My Eligibility",
                use_container_width=True
            ):

                payload = {
                    "notification_analysis": result,
                    "student_profile": profile,
                    "analysis_mode": mode or "unknown",
                    "scheme_name": selected_scheme
                }

                with st.spinner(
                    f"Checking eligibility for {selected_scheme}..."
                ):

                    try:
                        response = requests.post(
                            f"{API_URL}/match-eligibility",
                            json=payload,
                            timeout=60
                        )

                        if response.ok:
                            match_data = response.json()

                            if match_data.get("success"):
                                st.session_state.eligibility_result = (
                                    match_data.get("result", {})
                                )

                                st.success(
                                    f"Eligibility comparison completed "
                                    f"for {selected_scheme}!"
                                )
                            else:
                                st.session_state.eligibility_result = None
                                st.error(
                                    match_data.get(
                                        "message",
                                        "Eligibility comparison failed."
                                    )
                                )

                        else:
                            st.session_state.eligibility_result = None
                            st.error(
                                f"Eligibility check failed: {response.text}"
                            )

                    except requests.RequestException as error:
                        st.error(
                            f"Could not connect to backend: {error}"
                        )


        # =================================================
        # 13. ELIGIBILITY REPORT
        # =================================================

        eligibility_result = st.session_state.eligibility_result

        if eligibility_result:

            st.divider()
            st.subheader("📊 Your Eligibility Report")

            st.write(
                "**Selected Scholarship:**",
                eligibility_result.get(
                    "scheme_name",
                    st.session_state.get(
                        "selected_scholarship",
                        "Not specified"
                    )
                )
            )

            overall_status = eligibility_result.get(
                "overall_status",
                "Unknown"
            )

            st.header(overall_status)

            col1, col2, col3, col4 = st.columns(4)

            col1.metric(
                "Total Criteria",
                eligibility_result.get("total_criteria", 0)
            )

            col2.metric(
                "Matched",
                eligibility_result.get("matched_criteria", 0)
            )

            col3.metric(
                "Not Matched",
                eligibility_result.get("unmatched_criteria", 0)
            )

            col4.metric(
                "Unverified",
                eligibility_result.get("unverified_criteria", 0)
            )

            st.markdown("### Detailed Criteria Analysis")

            criteria_results = eligibility_result.get(
                "criteria_results",
                []
            )

            if criteria_results:

                for index, item in enumerate(criteria_results, start=1):

                    with st.expander(
                        f"{index}. {item.get('criterion', 'Criterion')}"
                    ):

                        status = item.get("status", "Unknown")

                        explanation = (
                            item.get("explanation")
                            or item.get("reason")
                            or "No explanation was returned by the backend."
                        )

                        evidence = (
                            item.get("source_evidence")
                            or item.get("evidence")
                            or "No supporting evidence was extracted."
                        )

                        st.write("**Status:**", status)

                        st.write("**Explanation:**")
                        st.write(explanation)

                        st.write("**Evidence from Notification:**")

                        if isinstance(evidence, list):
                            if evidence:
                                for sentence in evidence:
                                    st.info(str(sentence))
                            else:
                                st.warning("No supporting evidence found.")
                        else:
                            st.info(str(evidence))

            else:

                st.warning(
                    "No individual eligibility criteria were returned. "
                    "Please inspect the backend response."
                )

            st.info(
                eligibility_result.get(
                    "disclaimer",
                    "This is a preliminary assessment, not an official "
                    "eligibility decision. Verify all conditions against "
                    "the original official notification."
                )
            )


# =====================================================
# 14. FOOTER
# =====================================================

st.divider()

st.markdown(
    """
    <div class="n2a-footer">
        <strong>NOTICE2ACTION AI</strong><br>
        INNOVATE INDIA 2026 | Team DevHarbour
        <br>
        From Notifications to Action.
    </div>
    """,
    unsafe_allow_html=True
)