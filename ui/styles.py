"""Shared CSS for the AdaptiveLearn workspace and authentication experience."""

from ui.theme import DESIGN, THEME

_THEME_CSS = ":root {" + ";".join(
    f"--al-{name}:{value}" for name, value in (THEME | DESIGN).items()
) + (
    ";--al-card:var(--al-surface);--al-elevated:var(--al-surface-subtle)"
    ";--al-auth-bg:var(--al-bg);--al-auth-card:var(--al-surface)"
    ";--al-purple:var(--al-accent);--al-purple-dark:var(--al-link)"
    ";--al-success:var(--al-success-text);--al-warning:var(--al-warning-text)"
    ";--al-error:var(--al-error-text)"
    "}"
)

GLOBAL_CSS = r"""
<style>
/* AL_THEME_TOKENS */
html, body, [data-testid="stAppViewContainer"], .stApp { background:var(--al-bg); color:var(--al-text); }
body, button, input, textarea { font-family:var(--al-font-family); }
html { color-scheme:light; }
[data-testid="stAppViewContainer"] { background:var(--al-bg); }
[data-testid="stHeader"] { background:transparent; border-bottom:0; }
[data-testid="stToolbar"] { right:1rem; }
footer, #MainMenu { visibility:hidden; }
[data-testid="stSidebar"] { background:var(--al-sidebar); border-right:1px solid var(--al-border); }
[data-testid="stSidebar"] > div:first-child { background:var(--al-sidebar); }
[data-testid="stSidebar"] [data-testid="stSidebarContent"] { box-sizing:border-box; display:flex; height:100vh; min-height:100vh; flex-direction:column; overflow-y:auto; padding-top:0!important; }
[data-testid="stSidebar"] [data-testid="stSidebarContent"] > [data-testid="stSidebarUserContent"] { display:flex!important; flex:1 0 auto; flex-direction:column; min-height:0; padding-bottom:0!important; }
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > div { display:flex; flex:1 0 auto; flex-direction:column; min-height:0; }
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] > div > [data-testid="stVerticalBlock"] { display:flex!important; flex:1 0 auto; flex-direction:column; min-height:0; }
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] > div:has(.st-key-adaptivelearn-sidebar-brand) { order:0; flex:0 0 auto; }
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] > div:has(.st-key-adaptivelearn-sidebar-navigation) { order:1; flex:1 0 auto; padding:.35rem .7rem .8rem; }
[data-testid="stSidebar"] .st-key-adaptivelearn-sidebar-brand,
[data-testid="stSidebar"] .st-key-adaptivelearn-sidebar-navigation,
[data-testid="stSidebar"] .st-key-adaptivelearn-sidebar-bottom { display:flex!important; width:100%; flex-direction:column; }
[data-testid="stSidebar"] .st-key-adaptivelearn-sidebar-brand { flex:0 0 auto; }
[data-testid="stSidebar"] .st-key-adaptivelearn-sidebar-navigation { flex:1 0 auto; }
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] [data-testid="stVerticalBlock"] > div:has(.st-key-adaptivelearn-sidebar-bottom) { order:2; flex:0 0 auto; }
[data-testid="stSidebar"] .st-key-adaptivelearn-sidebar-bottom { flex:0 0 auto; }
[data-testid="stSidebar"] .st-key-adaptivelearn-sidebar-navigation > [data-testid="stElementContainer"],
[data-testid="stSidebar"] .st-key-adaptivelearn-sidebar-bottom > [data-testid="stElementContainer"] { flex:0 0 auto; margin:0!important; }
[data-testid="stSidebar"] .st-key-adaptivelearn-sidebar-navigation [data-testid="stMarkdownContainer"],
[data-testid="stSidebar"] .st-key-adaptivelearn-sidebar-bottom [data-testid="stMarkdownContainer"] { margin-bottom:0!important; }
[data-testid="stSidebarNav"] li { margin:.18rem 0; }
[data-testid="stSidebarNav"] a,
[data-testid="stSidebar"] .st-key-adaptivelearn-sidebar-navigation a { min-height:2.55rem; padding:.55rem .8rem; border:1px solid transparent; border-radius:.7rem; color:var(--al-muted); transition:background .15s ease,border-color .15s ease,color .15s ease; }
[data-testid="stSidebarNav"] a:hover,
[data-testid="stSidebar"] .st-key-adaptivelearn-sidebar-navigation a:hover { background:var(--al-elevated); border-color:var(--al-border); color:var(--al-text); }
[data-testid="stSidebarNav"] a[aria-current="page"],
[data-testid="stSidebar"] .st-key-adaptivelearn-sidebar-navigation a[aria-current="page"] { background:var(--al-surface-selected); border-color:var(--al-focus); border-left-width:3px; color:var(--al-text); font-weight:650; }
[data-testid="stSidebarNav"] a:focus-visible,
[data-testid="stSidebar"] .st-key-adaptivelearn-sidebar-navigation a:focus-visible,
button:focus-visible, input:focus-visible, textarea:focus-visible { outline:2px solid var(--al-focus)!important; outline-offset:2px!important; }
[data-testid="stSidebarNav"] [data-testid="stSidebarNavSeparator"] { border-color:var(--al-border); }
[data-testid="stSidebar"] .adaptivelearn-brand { display:flex; align-items:center; gap:.8rem; padding:.8rem .6rem 1.05rem; border-bottom:1px solid var(--al-border); margin-bottom:.4rem; }
.adaptivelearn-brand-icon { display:grid; place-items:center; width:2.5rem; height:2.5rem; border:1px solid var(--al-accent-hover); border-radius:.8rem; background:var(--al-surface-selected); color:var(--al-accent-text); font-size:1.15rem; }
.adaptivelearn-brand strong { display:block; color:var(--al-text); font-size:.92rem; letter-spacing:-.02em; }
.adaptivelearn-brand small { display:block; margin-top:.18rem; color:var(--al-muted); font-size:.7rem; }
[data-testid="stSidebar"] .adaptivelearn-section-label { margin:1rem 0 .45rem; color:var(--al-muted); font-size:.64rem; font-weight:700; letter-spacing:.14em; }
[data-testid="stSidebar"] .adaptivelearn-account { display:flex; align-items:center; gap:.65rem; padding:.75rem; border:1px solid var(--al-border); border-radius:.75rem; background:var(--al-surface-subtle); }
[data-testid="stSidebar"] .adaptivelearn-account strong { display:block; color:var(--al-text); font-size:.82rem; }
[data-testid="stSidebar"] .adaptivelearn-account small { color:var(--al-muted); font-size:.7rem; }
.adaptivelearn-status-dot { width:.5rem; height:.5rem; flex:0 0 auto; border-radius:50%; background:var(--al-success-text); box-shadow:0 0 0 3px var(--al-success-bg); }
[data-testid="stMainBlockContainer"] { width:100%; max-width:1440px; padding:2.3rem clamp(1.2rem,3vw,3rem) 4rem; }
h1,h2,h3,h4 { color:var(--al-text)!important; letter-spacing:-.035em; }
h1 { font-size:2.2rem!important; font-weight:650!important; line-height:1.15!important; margin:.2rem 0 .45rem!important; }
h2 { font-size:1.35rem!important; font-weight:620!important; margin:1.9rem 0 .9rem!important; }
h3 { font-size:1.05rem!important; font-weight:620!important; }
p, [data-testid="stMarkdownContainer"] { color:var(--al-text); }
.stMarkdown a, [data-testid="stMarkdownContainer"] a { color:var(--al-link); text-decoration-thickness:.08em; text-underline-offset:.16em; }
.stMarkdown a:hover, [data-testid="stMarkdownContainer"] a:hover { color:var(--al-focus); }
.stMarkdown a:focus-visible, [data-testid="stMarkdownContainer"] a:focus-visible { outline:2px solid var(--al-focus); outline-offset:2px; border-radius:.15rem; }
.al-kicker { margin:.3rem 0 .6rem; color:var(--al-accent); font-size:.68rem; font-weight:750; letter-spacing:.15em; text-transform:uppercase; }
.al-page-description { margin:.1rem 0 1.45rem; max-width:760px; color:var(--al-muted)!important; font-size:.98rem; line-height:1.6; }
small,.stCaption,[data-testid="stCaptionContainer"] { color:var(--al-muted)!important; }
[data-testid="stMetric"] { min-height:6.3rem; padding:1rem 1.1rem; border:1px solid var(--al-border); border-radius:.9rem; background:var(--al-card); }
[data-testid="stMetricLabel"] { color:var(--al-muted)!important; font-size:.75rem!important; }
[data-testid="stMetricValue"] { color:var(--al-text)!important; font-size:1.55rem!important; font-weight:650!important; }
[data-testid="stVerticalBlockBorderWrapper"] { border-color:var(--al-border)!important; border-radius:.95rem!important; background:var(--al-card); }
[data-testid="stVerticalBlockBorderWrapper"] { box-shadow:var(--al-shadow-card); }
[data-testid="stExpander"] { border:1px solid var(--al-border); border-radius:.85rem; background:var(--al-card); }
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary * { color:var(--al-text)!important; }
[data-testid="stAlert"] { border-radius:.8rem; border-width:1px; }
div.stButton > button, [data-testid="stFormSubmitButton"] button { min-height:2.55rem; border:1px solid var(--al-control-border); border-radius:var(--al-radius-control); background:var(--al-surface); color:var(--al-text); font-weight:600; transition:background .15s ease,border-color .15s ease,color .15s ease,box-shadow .15s ease; }
div.stButton > button:hover, [data-testid="stFormSubmitButton"] button:hover { border-color:var(--al-focus); background:var(--al-surface-hover); color:var(--al-text); }
div.stButton > button:active, [data-testid="stFormSubmitButton"] button:active { background:var(--al-surface-selected); }
div.stButton > button:focus-visible, [data-testid="stFormSubmitButton"] button:focus-visible { outline:2px solid var(--al-focus)!important; outline-offset:2px!important; }
div.stButton > button:disabled, [data-testid="stFormSubmitButton"] button:disabled { border-color:var(--al-border); background:var(--al-disabled-bg); color:var(--al-disabled-text); opacity:1; cursor:not-allowed; }
div.stButton > button[kind="primary"], [data-testid="stFormSubmitButton"] button[kind="primary"] { border-color:var(--al-focus); background:var(--al-accent); color:var(--al-text); }
div.stButton > button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] button[kind="primary"]:hover { border-color:var(--al-focus); background:var(--al-accent-hover); color:var(--al-text); }
[data-testid="stBaseButton-secondary"], [data-testid="stBaseButton-tertiary"] { border:1px solid var(--al-control-border)!important; background:var(--al-surface)!important; color:var(--al-text)!important; }
[data-testid="stBaseButton-secondary"]:hover, [data-testid="stBaseButton-tertiary"]:hover { border-color:var(--al-focus)!important; background:var(--al-surface-hover)!important; color:var(--al-text)!important; }
[data-testid="stBaseButton-primary"] { border:1px solid var(--al-focus)!important; background:var(--al-accent)!important; color:var(--al-text)!important; }
[data-testid="stBaseButton-primary"]:hover { border-color:var(--al-focus)!important; background:var(--al-accent-hover)!important; color:var(--al-text)!important; }
[data-testid^="stBaseButton-"]:disabled { border-color:var(--al-border)!important; background:var(--al-disabled-bg)!important; color:var(--al-disabled-text)!important; opacity:1!important; }
[data-testid^="stBaseButton-"] svg { color:inherit!important; fill:currentColor!important; }
[data-testid^="stBaseButton-"]:focus-visible { outline:2px solid var(--al-focus)!important; outline-offset:2px!important; }
input,textarea,[data-baseweb="select"] > div { border-color:var(--al-control-border)!important; border-radius:var(--al-radius-control)!important; background:var(--al-surface)!important; color:var(--al-text)!important; }
input::placeholder, textarea::placeholder { color:var(--al-muted)!important; opacity:1!important; }
input:focus,textarea:focus,[data-baseweb="select"] > div:focus-within { border-color:var(--al-focus)!important; box-shadow:0 0 0 2px var(--al-surface-selected)!important; }
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] *, [data-testid="stTextInput"] label, [data-testid="stTextArea"] label { color:var(--al-label)!important; opacity:1!important; }
[data-testid="stTextInputRootElement"] button, [data-testid="stTextArea"] button, [data-testid="stChatInput"] button { color:var(--al-label)!important; }
[data-testid="stTextInputRootElement"] button:hover, [data-testid="stTextArea"] button:hover { background:var(--al-surface-hover)!important; }
[data-testid="stTextInputRootElement"] button:focus-visible, [data-testid="stTextArea"] button:focus-visible { outline:2px solid var(--al-focus)!important; outline-offset:1px!important; }
[data-testid="stCheckbox"] label, [data-testid="stRadio"] label, [data-testid="stToggle"] label { color:var(--al-text)!important; }
[data-testid="stSelectbox"] [data-baseweb="select"] > div { background:var(--al-surface)!important; color:var(--al-text)!important; }
[data-testid="stSelectbox"] [role="group"] { border:1px solid var(--al-control-border)!important; border-radius:var(--al-radius-control)!important; background:var(--al-surface)!important; color:var(--al-text)!important; }
[data-testid="stSelectbox"] [role="group"]:focus-within { border-color:var(--al-focus)!important; box-shadow:0 0 0 2px var(--al-surface-selected)!important; }
[data-testid="stSelectbox"] input[role="combobox"] { border:0!important; background:transparent!important; color:var(--al-text)!important; box-shadow:none!important; }
[data-testid="stSelectbox"] button[aria-haspopup="listbox"] { border:0!important; background:transparent!important; color:var(--al-text)!important; }
[data-testid="stSelectbox"] button[aria-haspopup="listbox"]:hover { background:var(--al-surface-hover)!important; color:var(--al-text)!important; }
[data-testid="stSelectboxVirtualDropdown"], [role="listbox"] { border:1px solid var(--al-control-border)!important; border-radius:var(--al-radius-control)!important; background:var(--al-surface)!important; color:var(--al-text)!important; box-shadow:var(--al-shadow-card)!important; }
[data-testid="stSelectboxVirtualDropdown"] [role="option"], [role="listbox"] [role="option"] { background:var(--al-surface)!important; color:var(--al-text)!important; }
[data-testid="stSelectboxVirtualDropdown"] [role="option"]:hover,
[data-testid="stSelectboxVirtualDropdown"] [role="option"][aria-selected="true"],
[role="listbox"] [role="option"]:hover,
[role="listbox"] [role="option"][aria-selected="true"] { background:var(--al-surface-selected)!important; color:var(--al-text)!important; }
[data-baseweb="popover"], [data-baseweb="menu"], [data-baseweb="select"] [role="listbox"] { border:1px solid var(--al-control-border)!important; background:var(--al-surface)!important; color:var(--al-text)!important; }
[data-baseweb="popover"] *, [data-baseweb="menu"] *, [data-baseweb="select"] [role="option"] { color:var(--al-text)!important; }
[data-baseweb="select"] [role="option"]:hover, [data-baseweb="select"] [role="option"][aria-selected="true"] { background:var(--al-surface-selected)!important; }
[data-baseweb="tooltip"], [role="tooltip"] { border:1px solid var(--al-control-border)!important; background:var(--al-surface)!important; color:var(--al-text)!important; }
[data-testid="stTabs"] button { color:var(--al-muted)!important; }
[data-testid="stTabs"] button[aria-selected="true"] { color:var(--al-text)!important; border-bottom-color:var(--al-accent-text)!important; }
[data-testid="stTabs"] [role="tablist"] { border-bottom-color:var(--al-border)!important; }
[data-testid="stTabs"] button:focus-visible { outline:2px solid var(--al-focus)!important; outline-offset:2px!important; }
[data-testid="stProgressBar"] > div { background:var(--al-surface-subtle); }
[data-testid="stProgressBar"] > div > div { background:var(--al-accent); }
[data-testid="stSlider"] [role="slider"] { border-color:var(--al-accent-text)!important; box-shadow:0 0 0 2px var(--al-surface-selected)!important; }
[data-testid="stDataFrame"], [data-testid="stTable"] { color:var(--al-text)!important; }
[data-testid="stAlert"] { border:1px solid var(--al-border)!important; border-radius:.8rem!important; background:var(--al-surface)!important; color:var(--al-text)!important; }
[data-testid="stAlertContainer"] { border:1px solid var(--al-border)!important; border-radius:.8rem!important; }
[data-testid="stAlertContentInfo"] { background:var(--al-surface-subtle)!important; color:var(--al-text)!important; }
[data-testid="stAlertContentSuccess"] { background:var(--al-success-bg)!important; color:var(--al-success-text)!important; }
[data-testid="stAlertContentWarning"] { background:var(--al-warning-bg)!important; color:var(--al-warning-text)!important; }
[data-testid="stAlertContentError"] { background:var(--al-error-bg)!important; color:var(--al-error-text)!important; }
[data-testid^="stAlertContent"] *, [data-testid="stAlertContainer"] p { color:inherit!important; }
[data-testid^="stAlertContent"] svg { color:inherit!important; fill:currentColor!important; }
[data-testid="stVegaLiteChart"], .vega-embed { background:transparent!important; }
.vg-tooltip { border:1px solid var(--al-control-border)!important; background:var(--al-surface)!important; color:var(--al-text)!important; box-shadow:0 2px 8px var(--al-shadow)!important; }
.vg-tooltip table, .vg-tooltip th, .vg-tooltip td { color:var(--al-text)!important; }
[data-testid="stChatMessage"] { max-width:920px; padding:.9rem 1rem; margin:.7rem auto; border:1px solid var(--al-border); border-radius:1rem; background:var(--al-card); }
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) { background:var(--al-surface-selected); border-color:var(--al-accent-hover); }
[data-testid="stChatMessage"] [data-testid="stMarkdownContainer"] { line-height:1.72; }
[data-testid="stChatMessage"] pre { border:1px solid var(--al-border); border-radius:.7rem; background:var(--al-surface-subtle); color:var(--al-text); }
[data-testid="stChatInput"] { max-width:920px; margin-left:auto; margin-right:auto; border-color:var(--al-border); border-radius:.9rem; background:var(--al-card); }
[data-testid="stChatInput"] > div { border:1px solid var(--al-control-border)!important; border-radius:.9rem!important; background:var(--al-surface)!important; }
[data-testid="stChatInputSubmitButton"] { border:1px solid var(--al-focus)!important; border-radius:.65rem!important; background:var(--al-accent)!important; color:var(--al-text)!important; }
[data-testid="stChatInputSubmitButton"]:disabled { border-color:var(--al-border)!important; background:var(--al-disabled-bg)!important; color:var(--al-disabled-text)!important; }
[data-testid="stChatInputSubmitButton"] svg { color:inherit!important; fill:currentColor!important; }
[role="radiogroup"] label { padding:.65rem .8rem; border:1px solid var(--al-control-border); border-radius:.7rem; background:var(--al-surface); color:var(--al-text); transition:border-color .15s ease,background .15s ease; }
[role="radiogroup"] label:hover { border-color:var(--al-focus); background:var(--al-surface-hover); }
[data-testid="stRadio"] [role="radiogroup"] { width:100%; gap:.55rem; }
[data-testid="stRadio"] [role="radiogroup"] label { width:100%; min-height:3rem; align-items:center; white-space:normal; }
[data-testid="stRadio"] [role="radiogroup"] label:has([role="radio"][aria-checked="true"]) { border-color:var(--al-accent-text); background:var(--al-surface-selected); box-shadow:0 0 0 1px var(--al-accent-hover); }
[data-testid="stRadio"] [role="radiogroup"] label > div:last-child { overflow-wrap:anywhere; }
.al-empty-state { display:grid; justify-items:center; gap:.4rem; padding:2rem 1.2rem; border:1px dashed var(--al-control-border); border-radius:.9rem; background:var(--al-surface); text-align:center; box-shadow:var(--al-shadow-card); }
.al-empty-state strong { color:var(--al-text); }
.al-empty-state span { max-width:520px; color:var(--al-muted); font-size:.88rem; }
.al-empty-mark { display:grid; place-items:center; width:2rem; height:2rem; margin-bottom:.3rem; border-radius:50%; background:var(--al-surface-selected); color:var(--al-accent-text); font-size:1.2rem; }
.al-status { display:inline-flex; align-items:center; padding:.28rem .6rem; border:1px solid var(--al-border); border-radius:99px; font-size:.72rem; font-weight:650; }
.al-status-neutral { color:var(--al-muted); background:var(--al-elevated); }
.al-status-success { color:var(--al-success); border-color:var(--al-success-border); background:var(--al-success-bg); }
.al-status-warning { color:var(--al-warning); border-color:var(--al-warning-border); background:var(--al-warning-bg); }
.al-status-error { color:var(--al-error); border-color:var(--al-error-border); background:var(--al-error-bg); }
.st-key-lp-concept-grid .al-concept-status { display:flex; box-sizing:border-box; width:100%; height:220px; min-width:0; min-height:220px; max-height:220px; flex-direction:column; padding:.8rem; border:1px solid var(--al-border); border-radius:.85rem; background:var(--al-card); overflow:hidden; }
.st-key-lp-concept-grid .al-concept-status > strong { display:block; min-width:0; flex:0 0 auto; margin:0; color:var(--al-text); font-size:.85rem; line-height:1.35; overflow-wrap:anywhere; }
.st-key-lp-concept-grid .al-concept-count { display:block; min-width:0; flex:0 0 auto; margin:.15rem 0 .45rem; color:var(--al-muted); font-size:.72rem; }
.st-key-lp-concept-grid .al-concept-tags { display:flex; box-sizing:border-box; width:100%; min-width:0; min-height:0; flex:1 1 auto; flex-direction:column; align-items:stretch; gap:.35rem; overflow-y:auto; overflow-x:hidden; overscroll-behavior:contain; scrollbar-color:var(--al-control-border) transparent; scrollbar-width:thin; }
.st-key-lp-concept-grid .al-concept-tag { box-sizing:border-box; min-width:0; flex:0 0 auto; padding:.28rem .5rem; border:1px solid var(--al-border); border-radius:.55rem; background:var(--al-elevated); color:var(--al-text); font-size:.72rem; line-height:1.4; overflow-wrap:anywhere; }
.st-key-lp-concept-grid .al-concept-empty { display:block; flex:0 0 auto; color:var(--al-muted); font-size:.8rem; line-height:1.5; }
.st-key-lp-concept-grid .al-concept-tags::-webkit-scrollbar { width:.38rem; }
.st-key-lp-concept-grid .al-concept-tags::-webkit-scrollbar-track { background:transparent; }
.st-key-lp-concept-grid .al-concept-tags::-webkit-scrollbar-thumb { border-radius:99px; background:var(--al-control-border); }
.st-key-lp-concept-grid .al-concept-success > strong { color:var(--al-success); }.st-key-lp-concept-grid .al-concept-warning > strong { color:var(--al-warning); }.st-key-lp-concept-grid .al-concept-error > strong { color:var(--al-error); }.st-key-lp-concept-grid .al-concept-info > strong { color:var(--al-accent); }
.lp-recommendation-content { display:grid; width:100%; min-width:0; grid-template-columns:minmax(0,1fr); gap:.5rem; margin:0 0 .45rem; }
.lp-recommendation-topline,.lp-recommendation-labels { display:flex; flex-wrap:wrap; align-items:center; gap:.5rem; }
.lp-recommendation-topline { min-width:0; justify-content:space-between; }
.lp-eyebrow,.lp-section-label { color:var(--al-muted); font-size:.68rem; font-weight:750; letter-spacing:.11em; text-transform:uppercase; }
.lp-topic-heading { min-width:0; margin:0!important; font-size:clamp(1.55rem,3vw,2.15rem)!important; line-height:1.16!important; overflow-wrap:anywhere; }
.lp-badge { display:inline-flex; align-items:center; min-height:1.65rem; padding:.28rem .62rem; border:1px solid var(--al-border); border-radius:999px; background:var(--al-elevated); color:var(--al-text); font-size:.72rem; font-weight:650; }
.lp-priority-high { border-color:var(--al-error-border); background:var(--al-error-bg); color:var(--al-error); }
.lp-priority-medium { border-color:var(--al-warning-border); background:var(--al-warning-bg); color:var(--al-warning); }
.lp-priority-low,.lp-subject-badge { border-color:var(--al-accent-hover); background:var(--al-surface-selected); color:var(--al-accent-text); }
.lp-difficulty-badge { color:var(--al-label); }
.lp-recommendation-explanation { box-sizing:border-box; width:100%; min-width:0; padding:.7rem .85rem; border-left:3px solid var(--al-accent); border-radius:.2rem .65rem .65rem .2rem; background:var(--al-surface-hover); }
.lp-recommendation-reason { width:100%; max-width:none; margin:.3rem 0 0; padding:0; border:0; background:transparent; color:var(--al-text); font-size:.9rem; line-height:1.55; overflow-wrap:anywhere; }
.lp-recommendation-reason strong { color:var(--al-accent-text); font-weight:750; }
.lp-recommendation-details { display:grid; min-width:0; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.55rem; }
.lp-recommendation-detail { box-sizing:border-box; min-width:0; padding:.65rem .8rem; border:1px solid var(--al-border); border-radius:.65rem; background:var(--al-surface-subtle); }
.lp-recommendation-detail p { margin:.3rem 0 0; color:var(--al-text); font-size:.84rem; line-height:1.5; overflow-wrap:anywhere; }
.st-key-lp-overview-grid [data-testid="stVerticalBlock"] { height:100%; }
.st-key-lp-overview-grid [data-testid="stVerticalBlockBorderWrapper"] { height:100%; min-height:7.4rem; padding:.8rem .9rem; border-radius:.8rem; background:var(--al-card); }
.st-key-lp-overview-grid [data-testid="stMetricLabel"] { min-height:2.4rem; align-items:flex-start; overflow-wrap:anywhere; }
.st-key-lp-overview-grid [data-testid="stMetricValue"] { min-width:0; overflow-wrap:anywhere; }
.st-key-lp-overview-demonstrated [data-testid="stMetricValue"] { color:var(--al-accent)!important; }
.st-key-lp-overview-demonstrated [data-testid="stVerticalBlockBorderWrapper"] { border-color:var(--al-accent-hover); background:var(--al-surface-selected); }
.st-key-lp-subject-control,
.st-key-lp-diagnostic-card { --lp-select-control-width:250px; --lp-select-control-height:2.5rem; }
.st-key-lp-subject-control,
.st-key-lp-diagnostic-controls { width:min(100%,var(--lp-select-control-width)); }
.st-key-lp-subject-control { display:flex; flex-direction:column; align-items:flex-end; }
.st-key-lp-subject-control [data-testid="stWidgetLabel"] { justify-content:flex-end; text-align:right; }
.st-key-lp-subject-control [data-testid="stSelectbox"],
.st-key-lp-diagnostic-controls [data-testid="stSelectbox"] { width:100%; }
.st-key-lp-subject-control [data-baseweb="select"],
.st-key-lp-diagnostic-controls [data-baseweb="select"] { box-sizing:border-box; height:var(--lp-select-control-height); min-height:var(--lp-select-control-height); }
.st-key-lp-diagnostic-card [data-testid="stVerticalBlockBorderWrapper"] { padding:.7rem .9rem; border-radius:.85rem; background:var(--al-card); }
.st-key-lp-diagnostic-card [data-testid="stColumn"] { min-width:0; }
.st-key-lp-diagnostic-card [data-testid="stMarkdownContainer"] { overflow-wrap:anywhere; }
.st-key-lp-diagnostic-controls { margin-left:auto; }
.st-key-lp-diagnostic-action { width:100%; padding-top:.15rem; }
.st-key-lp-diagnostic-controls div.stButton > button { width:100%; min-height:2.65rem; }
.st-key-lp-diagnostic-action div.stButton > button,
.st-key-lp-practice-action div.stButton > button,
.st-key-lp-generate-action div.stButton > button { width:auto; min-width:8.5rem; min-height:2.55rem; padding:.5rem .9rem; }
.st-key-lp-diagnostic-action div.stButton > button { width:100%; min-height:2.65rem; }
.st-key-lp-concept-grid { display:block; width:100%; overflow:hidden; }
.st-key-lp-concept-grid [data-testid="stHorizontalBlock"] { display:grid!important; width:100%; grid-template-columns:repeat(4,minmax(0,1fr)); grid-auto-rows:220px; align-items:stretch; gap:.75rem; overflow:hidden; }
.st-key-lp-concept-grid [data-testid="stColumn"] { display:flex; width:auto!important; min-width:0!important; flex:none!important; overflow:hidden; }
.st-key-lp-concept-grid [data-testid="stColumn"] > div { width:100%; height:100%; min-width:0; min-height:0; overflow:hidden; }
.st-key-lp-concept-grid [data-testid="stElementContainer"] { width:100%; height:100%; min-width:0; min-height:0; overflow:hidden; }
.st-key-lp-recommendation-card [data-testid="stVerticalBlockBorderWrapper"] { padding:1rem 1.1rem; border-radius:.85rem; background:var(--al-card); }
.st-key-lp-recommendation-actions { padding-top:.25rem; }
.st-key-lp-recommendation-actions [data-testid="stHorizontalBlock"] { display:flex!important; align-items:center; justify-content:flex-end; flex-wrap:wrap; gap:.6rem; }
.st-key-lp-recommendation-actions [data-testid="stColumn"] { width:auto!important; min-width:0!important; flex:0 0 auto!important; }
.st-key-lp-recommendation-actions [data-testid="stColumn"] > div { width:auto; }
.st-key-lp-recommendation-actions div.stButton > button { width:auto; min-width:9rem; min-height:2.65rem; padding:.5rem .9rem; }
.st-key-lp-recommendation-actions .st-key-lp-generate-action { margin-top:0; }
.st-key-lp-practice-action { margin:.2rem 0 .5rem; }
.st-key-lp-generate-action { margin-top:.5rem; }
[data-testid="stMarkdownContainer"] table { width:100%; table-layout:fixed; border-color:var(--al-border); }
[data-testid="stMarkdownContainer"] th,[data-testid="stMarkdownContainer"] td { padding:.55rem .6rem; border-color:var(--al-border); overflow-wrap:anywhere; }
[data-testid="stMarkdownContainer"] th:first-child,[data-testid="stMarkdownContainer"] td:first-child { width:42%; }
.dashboard-welcome-copy { margin-bottom:.8rem; }
.st-key-dashboard-stat-grid [data-testid="stVerticalBlock"] { height:100%; }
.st-key-dashboard-stat-grid [data-testid="stVerticalBlockBorderWrapper"] { height:100%; min-height:7.5rem; padding:.9rem 1rem; background:var(--al-card); }
.dashboard-stat-value { color:var(--al-text); font-size:1.65rem; font-weight:680; letter-spacing:-.035em; line-height:1.2; }
.st-key-dashboard-action-grid [data-testid="stVerticalBlockBorderWrapper"] { display:flex; height:100%; min-height:10.2rem; flex-direction:column; justify-content:space-between; padding:1rem 1.1rem; background:var(--al-card); }
.st-key-dashboard-action-grid .dashboard-tile-description,
.st-key-dashboard-subject-grid .dashboard-tile-description,
.st-key-dashboard-recommendation-grid .dashboard-tile-description { min-height:2.8rem; margin:.2rem 0 .65rem; color:var(--al-muted); font-size:.84rem; line-height:1.5; }
.st-key-dashboard-action-grid div.stButton > button,
.st-key-dashboard-subject-grid div.stButton > button,
.st-key-dashboard-recommendation-grid div.stButton > button { width:auto; min-width:8.5rem; min-height:2.55rem; padding:.5rem .9rem; }
.st-key-dashboard-subject-grid [data-testid="stVerticalBlockBorderWrapper"],
.st-key-dashboard-recommendation-grid [data-testid="stVerticalBlockBorderWrapper"] { display:flex; height:100%; min-height:22.5rem; flex-direction:column; padding:1rem; background:var(--al-card); }
.st-key-dashboard-subject-grid [data-testid="stMetric"] { min-height:5.5rem; padding:.7rem .8rem; }
.st-key-dashboard-subject-grid [data-testid="stMetricValue"] { font-size:1.35rem!important; }
.st-key-dashboard-subject-grid [data-testid="stProgress"] { min-height:2.5rem; }
.st-key-dashboard-subject-grid div.stButton,
.st-key-dashboard-recommendation-grid div.stButton { margin-top:auto; padding-top:.7rem; }
.st-key-dashboard-recommendation-grid [data-testid="stVerticalBlockBorderWrapper"] { min-height:12.5rem; }
.st-key-dashboard-recommendation-grid [data-testid="stMarkdownContainer"] h4 { min-height:2.7rem; margin:.15rem 0 .4rem; overflow-wrap:anywhere; }
.st-key-practice-empty-layout { width:100%; min-width:0; }
.st-key-practice-empty-layout [data-testid="stHorizontalBlock"]:has(.st-key-practice-workspace):has(.st-key-practice-settings) { align-items:stretch!important; }
.st-key-practice-active-layout { width:100%; min-width:0; }
.st-key-practice-active-layout [data-testid="stHorizontalBlock"]:has(.st-key-practice-workspace):has(.st-key-practice-settings) { align-items:stretch!important; }
.st-key-practice-empty-layout [data-testid="stColumn"],
.st-key-practice-active-layout [data-testid="stColumn"] { display:flex; min-width:0; }
.st-key-practice-empty-layout [data-testid="stColumn"] > [data-testid="stVerticalBlock"],
.st-key-practice-active-layout [data-testid="stColumn"] > [data-testid="stVerticalBlock"] { display:flex; width:100%; min-width:0; flex:1 1 auto; }
.st-key-practice-workspace,
.st-key-practice-settings { box-sizing:border-box; width:100%; min-width:0; }
.st-key-practice-empty-layout .st-key-practice-workspace,
.st-key-practice-empty-layout .st-key-practice-settings,
.st-key-practice-active-layout .st-key-practice-workspace,
.st-key-practice-active-layout .st-key-practice-settings { display:flex; align-self:stretch; flex:1 1 auto; }
.st-key-practice-empty-layout .st-key-practice-workspace[data-testid="stVerticalBlockBorderWrapper"],
.st-key-practice-empty-layout .st-key-practice-workspace > [data-testid="stVerticalBlockBorderWrapper"],
.st-key-practice-active-layout .st-key-practice-workspace[data-testid="stVerticalBlockBorderWrapper"],
.st-key-practice-active-layout .st-key-practice-workspace > [data-testid="stVerticalBlockBorderWrapper"] { box-sizing:border-box; display:flex; width:100%; flex:1 1 auto; align-self:stretch; padding:1.2rem; }
.st-key-practice-empty-layout .st-key-practice-workspace[data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
.st-key-practice-empty-layout .st-key-practice-workspace > [data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
.st-key-practice-empty-layout .st-key-practice-settings[data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
.st-key-practice-empty-layout .st-key-practice-settings > [data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
.st-key-practice-active-layout .st-key-practice-workspace[data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
.st-key-practice-active-layout .st-key-practice-workspace > [data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
.st-key-practice-active-layout .st-key-practice-settings[data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"],
.st-key-practice-active-layout .st-key-practice-settings > [data-testid="stVerticalBlockBorderWrapper"] > [data-testid="stVerticalBlock"] { box-sizing:border-box; width:100%; min-width:0; flex:1 1 auto; }
.st-key-practice-empty-layout .st-key-practice-settings[data-testid="stVerticalBlockBorderWrapper"],
.st-key-practice-empty-layout .st-key-practice-settings > [data-testid="stVerticalBlockBorderWrapper"],
.st-key-practice-active-layout .st-key-practice-settings[data-testid="stVerticalBlockBorderWrapper"],
.st-key-practice-active-layout .st-key-practice-settings > [data-testid="stVerticalBlockBorderWrapper"] { box-sizing:border-box; display:flex; width:100%; flex:1 1 auto; align-self:stretch; padding:1.2rem; }
.st-key-practice-workspace[data-testid="stVerticalBlockBorderWrapper"],
.st-key-practice-workspace > [data-testid="stVerticalBlockBorderWrapper"] { padding:1.2rem; }
.st-key-practice-settings[data-testid="stVerticalBlockBorderWrapper"],
.st-key-practice-settings > [data-testid="stVerticalBlockBorderWrapper"] { padding:1.2rem; }
.st-key-practice-settings h2 { margin:.15rem 0 .8rem!important; font-size:1.12rem!important; }
.st-key-practice-settings [data-testid="stSelectbox"] { width:100%; margin-bottom:.45rem; }
.st-key-practice-settings [data-testid="stSelectbox"] [data-baseweb="select"] { width:100%; min-height:2.65rem; }
.st-key-practice-settings [data-testid="stSelectbox"] [data-baseweb="select"] > div { box-sizing:border-box; height:2.65rem; min-height:2.65rem; }
.st-key-practice-settings [data-testid="stButton"] { box-sizing:border-box; width:10rem; max-width:100%; }
.st-key-practice-settings div.stButton > button { box-sizing:border-box; width:100%; min-width:0; max-width:100%; min-height:2.55rem; padding:.5rem .95rem; font-size:.9rem; line-height:1.25; white-space:nowrap; }
.st-key-practice-settings [data-testid="stHorizontalBlock"] { gap:.55rem; }
.st-key-practice-workspace [data-testid="stProgress"] { margin:.7rem 0 1.1rem; }
.st-key-practice-workspace [data-testid="stRadio"] [role="radiogroup"] { display:flex!important; box-sizing:border-box; width:100%; flex-direction:column!important; align-items:stretch!important; gap:.55rem; }
.st-key-practice-workspace [data-testid="stRadio"] [role="radiogroup"] label { box-sizing:border-box; display:flex!important; width:100%!important; min-width:100%; max-width:100%; min-height:3.6rem; flex:0 0 auto; align-self:stretch; align-items:center; white-space:normal; overflow-wrap:anywhere; }
.st-key-practice-workspace [data-testid="stMarkdownContainer"] h3 { margin:1rem 0; line-height:1.5!important; overflow-wrap:anywhere; }
.st-key-practice-workspace .al-kicker { margin:.2rem 0 .7rem; }
.st-key-practice-workspace .al-page-description { margin:.3rem 0; }
.st-key-practice-workspace [data-testid="stVerticalBlockBorderWrapper"] [data-testid="stVerticalBlockBorderWrapper"] { margin:.65rem 0; }
.st-key-practice-settings-toggle { box-sizing:border-box; display:flex; width:100%; min-width:0; justify-content:flex-end; }
.st-key-practice-settings-toggle[data-testid="stVerticalBlock"],
.st-key-practice-settings-toggle [data-testid="stVerticalBlock"] { box-sizing:border-box; display:flex; flex-direction:row; width:100%; min-width:0; justify-content:flex-end; align-items:center; }
.st-key-practice-settings-toggle [data-testid="stButton"],
.st-key-practice-settings-toggle-button { box-sizing:border-box; display:flex; width:2.65rem; min-width:2.65rem; max-width:2.65rem; height:2.65rem; flex:0 0 2.65rem; }
.st-key-practice-settings-toggle-button button,
.st-key-practice-settings-toggle .st-key-practice-settings-toggle-button button,
.st-key-practice-settings-toggle div.stButton > button { box-sizing:border-box; display:flex; width:2.65rem; min-width:2.65rem; max-width:2.65rem; height:2.65rem; min-height:2.65rem; flex:0 0 2.65rem; align-items:center; justify-content:center; gap:0; padding:0; }
.st-key-practice-question-navigation [data-testid="stButton"] { width:fit-content; max-width:100%; }
.st-key-practice-question-navigation div.stButton > button { box-sizing:border-box; width:6rem; min-width:6rem; max-width:6rem; min-height:2.55rem; padding:.5rem .75rem; font-size:.9rem; line-height:1.25; white-space:nowrap; }
.st-key-practice-submit-action { margin-top:.65rem; }
.st-key-practice-submit-action [data-testid="stButton"] { width:fit-content; max-width:100%; }
.st-key-practice-submit-action div.stButton > button { box-sizing:border-box; width:12.75rem; min-width:12.75rem; max-width:100%; min-height:2.55rem; padding:.5rem .95rem; font-size:.9rem; line-height:1.25; white-space:nowrap; }
.st-key-progress-overview-card [data-testid="stHorizontalBlock"]:has([data-testid="stSelectbox"]) { align-items:center; }
.st-key-progress-detail-grid [data-testid="stHorizontalBlock"] { align-items:stretch; }
.st-key-progress-detail-grid [data-testid="stColumn"] { display:flex; min-width:0; }
.st-key-progress-concept-tile,
.st-key-progress-trends-tile { position:relative; box-sizing:border-box; display:flex; width:100%; min-width:0; min-height:14rem; flex:1 1 auto; flex-direction:column; padding:1.25rem; border:1px solid var(--al-border); border-radius:.95rem; background:var(--al-card); transition:border-color .15s ease,background .15s ease; }
.st-key-progress-concept-tile:hover,
.st-key-progress-trends-tile:hover { border-color:var(--al-accent-hover); background:var(--al-surface-hover); }
.st-key-progress-concept-tile .al-progress-tile-content,
.st-key-progress-trends-tile .al-progress-tile-content { display:flex; min-width:0; min-height:11.45rem; flex:1 1 auto; flex-direction:column; }
.al-progress-tile-heading { margin:0 0 .4rem; color:var(--al-text); font-size:1.05rem; font-weight:650; line-height:1.35; overflow-wrap:anywhere; }
.al-progress-tile-description { color:var(--al-muted); font-size:.82rem; line-height:1.5; overflow-wrap:anywhere; }
.al-progress-tile-summary { display:flex; flex-direction:column; gap:.32rem; margin-top:.8rem; color:var(--al-text); font-size:.78rem; line-height:1.45; overflow-wrap:anywhere; }
.al-progress-tile-stat { color:var(--al-text); font-weight:550; }
.al-progress-tile-counts { display:flex; flex-wrap:wrap; gap:.3rem .65rem; color:var(--al-muted); }
.al-progress-tile-status { color:var(--al-accent); font-weight:650; }
.al-progress-tile-change { color:var(--al-muted); }
.al-progress-tile-empty { color:var(--al-muted); }
.al-progress-tile-footer { margin-top:auto; padding-top:.9rem; color:var(--al-accent); font-size:.74rem; font-weight:600; }
.st-key-progress-concept-tile .st-key-progress-concept-tile-button,
.st-key-progress-trends-tile .st-key-progress-trends-tile-button { position:absolute; z-index:2; inset:0; width:100%; height:100%; }
.st-key-progress-concept-tile div.stButton > button,
.st-key-progress-trends-tile div.stButton > button { position:absolute; inset:0; box-sizing:border-box; width:100%; height:100%; min-height:100%; padding:0; border:0; border-radius:.95rem; background:transparent; color:transparent; opacity:.001; cursor:pointer; }
.st-key-progress-concept-tile div.stButton > button:hover,
.st-key-progress-trends-tile div.stButton > button:hover { border:0; background:transparent; color:transparent; }
.st-key-progress-concept-tile div.stButton > button:focus-visible,
.st-key-progress-trends-tile div.stButton > button:focus-visible { outline:2px solid var(--al-focus)!important; outline-offset:2px!important; }
.st-key-progress-overview-card [data-testid="stSelectbox"] { width:100%; }
.st-key-progress-overview-card [data-testid="stSelectbox"] label { margin-bottom:.35rem; }
@media (max-width: 760px) {
  .st-key-progress-detail-grid [data-testid="stHorizontalBlock"] { display:flex!important; flex-direction:column; gap:.8rem; }
  .st-key-progress-detail-grid [data-testid="stColumn"] { box-sizing:border-box; width:100%!important; min-width:0!important; flex:1 1 auto!important; }
}
.stApp:has(.st-key-auth-page-shell), [data-testid="stAppViewContainer"]:has(.st-key-auth-page-shell) { background:var(--al-auth-bg)!important; color:var(--al-text); }
body:has(.st-key-auth-page-shell) [data-testid="stHeader"] { background:var(--al-bg); border-bottom:0; }
body:has(.st-key-auth-page-shell) [data-testid="stDecoration"] { display:none!important; }
[data-testid="stMainBlockContainer"]:has(.st-key-auth-page-shell) { max-width:none; padding:0!important; }
.st-key-auth-page-shell { display:flex; min-height:calc(100vh - 3.5rem); align-items:center; justify-content:center; padding:1.5rem 1rem; }
.st-key-auth-form { width:min(100%,400px); margin:0 auto; color:var(--al-text); }
.st-key-auth-form h2 { margin:.65rem 0 .35rem!important; color:var(--al-text)!important; font-size:1.7rem!important; letter-spacing:-.025em; text-align:center; }
.st-key-auth-form [data-testid="stMarkdownContainer"] { color:var(--al-text); }
.auth-brand { margin-bottom:1.05rem; color:var(--al-text); font-size:1.2rem; font-weight:700; letter-spacing:-.015em; text-align:center; }
.auth-description { margin:0 0 1.1rem; color:var(--al-muted)!important; font-size:.9rem; text-align:center; }
.st-key-auth-form [data-testid="stForm"] { border:0!important; padding:0; background:transparent!important; box-shadow:none!important; }
.st-key-auth-form label,
.st-key-auth-form [data-testid="stWidgetLabel"],
.st-key-auth-form [data-testid="stWidgetLabel"] * { color:var(--al-label)!important; opacity:1!important; font-size:.84rem!important; font-weight:550!important; text-align:left; }
.st-key-auth-form [data-testid="stTextInputRootElement"] { min-height:2.8rem; border:1px solid var(--al-control-border)!important; border-radius:.55rem!important; background:var(--al-surface)!important; box-shadow:none!important; }
.st-key-auth-form [data-testid="stTextInputRootElement"] > div { background:transparent!important; }
.st-key-auth-form [data-testid="stTextInputRootElement"]:has(input:focus) { border-color:var(--al-focus)!important; box-shadow:0 0 0 2px var(--al-surface-selected)!important; }
.st-key-auth-form [data-testid="stTextInputRootElement"] input { min-height:2.7rem; border:0!important; border-radius:.55rem!important; background:transparent!important; color:var(--al-text)!important; box-shadow:none!important; }
.st-key-auth-form [data-testid="stTextInputRootElement"] input::placeholder { color:var(--al-muted)!important; opacity:1; }
.st-key-auth-form [data-testid="stTextInputIcon"] { display:none!important; }
.st-key-auth-form [data-testid="stTextInputRootElement"] > div:last-child:has(button[aria-label="Show password"],button[aria-label="Hide password"]) { display:none!important; }
.st-key-auth-form [data-testid="stTextInputRootElement"] button[aria-label="Show password"],
.st-key-auth-form [data-testid="stTextInputRootElement"] button[aria-label="Hide password"] { display:none!important; }
.st-key-auth-primary-action { display:flex!important; width:100%; flex-direction:column; align-items:center; }
.st-key-auth-primary-action > [data-testid="stElementContainer"] { width:min(100%,190px)!important; }
.st-key-auth-primary-action [data-testid="stFormSubmitButton"] { width:100%; margin-top:.35rem; }
.st-key-auth-primary-action [data-testid="stFormSubmitButton"] button { width:100%!important; min-height:2.9rem; border:1px solid var(--al-focus)!important; border-radius:var(--al-radius-pill)!important; background:var(--al-accent)!important; color:var(--al-text)!important; font-weight:650; }
.st-key-auth-primary-action [data-testid="stFormSubmitButton"] button * { color:var(--al-text)!important; }
.st-key-auth-primary-action [data-testid="stFormSubmitButton"] button:hover { border-color:var(--al-focus)!important; background:var(--al-accent-hover)!important; }
.st-key-auth-primary-action [data-testid="stFormSubmitButton"] button:disabled { border-color:var(--al-border)!important; background:var(--al-disabled-bg)!important; color:var(--al-disabled-text)!important; opacity:1; cursor:not-allowed; }
.st-key-auth-switch { display:flex!important; width:100%; flex-direction:column; align-items:center; margin-top:1rem; text-align:center; }
.st-key-auth-switch > [data-testid="stElementContainer"] { width:100%; }
.st-key-auth-switch > .st-key-auth-nav-signup,
.st-key-auth-switch > .st-key-auth-nav-signin { width:100%!important; }
.st-key-auth-switch .auth-switch-message { margin:0; color:var(--al-muted)!important; font-size:.84rem; line-height:1.5; text-align:center; }
.st-key-auth-switch [data-testid="stButton"] { display:flex; width:100%; justify-content:center; margin-top:.35rem; }
.st-key-auth-nav-signup button,
.st-key-auth-nav-signin button { box-sizing:border-box; display:inline-flex; width:auto!important; max-width:100%; min-height:2.4rem!important; align-items:center; justify-content:center; padding:.4rem .9rem!important; border:1px solid var(--al-accent-hover)!important; border-radius:999px!important; background:var(--al-surface-hover)!important; color:var(--al-link)!important; opacity:1!important; font-size:.9rem!important; font-weight:650!important; line-height:1.4; text-align:center; text-decoration:none; white-space:normal; box-shadow:none!important; cursor:pointer; }
.st-key-auth-nav-signup button *,
.st-key-auth-nav-signin button * { color:var(--al-link)!important; opacity:1!important; }
.st-key-auth-nav-signup button:hover,
.st-key-auth-nav-signin button:hover { border-color:var(--al-accent-hover)!important; background:var(--al-surface-selected)!important; color:var(--al-link)!important; text-decoration:none; }
.st-key-auth-nav-signup button:active,
.st-key-auth-nav-signin button:active { border-color:var(--al-link)!important; background:var(--al-accent-active)!important; color:var(--al-link)!important; }
.st-key-auth-nav-signup button:focus-visible,
.st-key-auth-nav-signin button:focus-visible { outline:2px solid var(--al-focus)!important; outline-offset:2px!important; }
.st-key-tutor-layout { width:100%; min-width:0; }
.st-key-tutor-settings { box-sizing:border-box; align-self:flex-start; width:100%; min-width:0; padding:1rem; border:1px solid var(--al-border); border-radius:.95rem; background:var(--al-card); }
.st-key-tutor-settings [data-testid="stSelectbox"] { width:100%; margin-bottom:.45rem; }
.st-key-tutor-settings [data-testid="stSelectbox"] [data-baseweb="select"] { width:100%; min-height:2.65rem; }
.st-key-tutor-settings [data-testid="stSelectbox"] [data-baseweb="select"] > div { box-sizing:border-box; height:2.65rem; min-height:2.65rem; }
.st-key-tutor-settings div.stButton > button { width:100%; }
.st-key-tutor-settings [data-testid="stCaptionContainer"] { line-height:1.5; }
.st-key-tutor-conversation { display:flex; min-width:0; min-height:calc(100vh - 8rem); flex-direction:column; }
.st-key-tutor-transcript { box-sizing:border-box; min-width:0; max-height:calc(100vh - 20rem); overflow-y:auto; overflow-x:hidden; overscroll-behavior:contain; scrollbar-color:var(--al-control-border) transparent; scrollbar-width:thin; }
.st-key-tutor-transcript::-webkit-scrollbar { width:.4rem; }
.st-key-tutor-transcript::-webkit-scrollbar-track { background:transparent; }
.st-key-tutor-transcript::-webkit-scrollbar-thumb { border-radius:99px; background:var(--al-control-border); }
.st-key-tutor-transcript [data-testid="stChatMessage"] { width:100%; max-width:none; box-sizing:border-box; }
.st-key-tutor-transcript [data-testid="stHorizontalBlock"] { gap:.6rem; }
.st-key-tutor-conversation [data-testid="stChatInput"] { box-sizing:border-box; width:100%; max-width:none; margin:.5rem 0 0; border:1px solid var(--al-border)!important; border-radius:.9rem!important; background:var(--al-card)!important; box-shadow:none!important; }
.st-key-tutor-conversation [data-testid="stChatInput"]:focus-within { border-color:var(--al-accent)!important; box-shadow:none!important; }
.st-key-tutor-conversation [data-testid="stChatInput"] [data-testid="stChatInputTextArea"] { border:0!important; outline:0!important; border-radius:0!important; background:transparent!important; color:var(--al-text)!important; box-shadow:none!important; }
.st-key-tutor-conversation [data-testid="stChatInput"] [data-testid="stChatInputTextArea"]:focus,
.st-key-tutor-conversation [data-testid="stChatInput"] [data-testid="stChatInputTextArea"]:focus-visible { border:0!important; outline:0!important; box-shadow:none!important; }
.al-tutor-welcome { width:100%; box-sizing:border-box; margin:.5rem 0 1rem; padding:1.35rem; border:1px solid var(--al-border); border-radius:var(--al-radius-card); background:var(--al-surface); box-shadow:var(--al-shadow-card); }
.al-tutor-welcome h3 { margin:.15rem 0 .45rem!important; }
.al-tutor-welcome p { margin:0; color:var(--al-muted); }
[data-testid="stVerticalBlockBorderWrapper"] h3 { max-width:100%; overflow-wrap:anywhere; line-height:1.45!important; }
@media (max-width: 900px) { [data-testid="stMainBlockContainer"] { padding:1.4rem 1.15rem 3rem; } }
@media (max-width: 760px) { [data-testid="stHorizontalBlock"] { flex-wrap:wrap; align-items:stretch; } [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { min-width:min(100%,260px)!important; flex:1 1 260px!important; } }
@media (max-width: 900px) {
  .st-key-tutor-layout [data-testid="stHorizontalBlock"]:has(.st-key-tutor-settings):has(.st-key-tutor-conversation) { display:flex!important; flex-direction:column; gap:.8rem; }
  .st-key-tutor-layout [data-testid="stHorizontalBlock"]:has(.st-key-tutor-settings):has(.st-key-tutor-conversation) > [data-testid="stColumn"] { box-sizing:border-box; width:100%!important; min-width:0!important; flex:1 1 auto!important; }
  .st-key-tutor-layout [data-testid="stHorizontalBlock"]:has(.st-key-tutor-settings):has(.st-key-tutor-conversation) > [data-testid="stColumn"]:has(.st-key-tutor-settings) { order:-1; }
  .st-key-tutor-transcript { max-height:calc(100vh - 21rem); }
  .st-key-tutor-conversation { min-height:70vh; }
}
@media (max-width: 600px) {
  .st-key-practice-question-navigation div.stButton > button { width:min(5rem,calc((100vw - 6rem)/2)); min-width:0; max-width:100%; }
  .st-key-practice-submit-action div.stButton > button { width:min(10.75rem,calc(100vw - 6rem)); min-width:0; max-width:100%; }
}
@media (max-width: 900px) {
  .st-key-practice-empty-layout [data-testid="stHorizontalBlock"]:has(.st-key-practice-workspace):has(.st-key-practice-settings) { display:flex!important; flex-direction:column; gap:.8rem; }
  .st-key-practice-empty-layout [data-testid="stHorizontalBlock"]:has(.st-key-practice-workspace):has(.st-key-practice-settings) > [data-testid="stColumn"] { box-sizing:border-box; width:100%!important; min-width:0!important; flex:1 1 auto!important; }
  .st-key-practice-empty-layout [data-testid="stHorizontalBlock"]:has(.st-key-practice-settings) > [data-testid="stColumn"]:has(.st-key-practice-settings) { order:-1; }
  .st-key-practice-active-layout [data-testid="stHorizontalBlock"]:has(.st-key-practice-workspace):has(.st-key-practice-settings) { display:flex!important; flex-direction:column; gap:.8rem; }
  .st-key-practice-active-layout [data-testid="stHorizontalBlock"]:has(.st-key-practice-workspace):has(.st-key-practice-settings) > [data-testid="stColumn"] { box-sizing:border-box; width:100%!important; min-width:0!important; flex:1 1 auto!important; }
  .st-key-practice-active-layout [data-testid="stHorizontalBlock"]:has(.st-key-practice-settings) > [data-testid="stColumn"]:has(.st-key-practice-settings) { order:-1; }
}
@media (max-width: 600px) { h1 { font-size:1.8rem!important; } [data-testid="stMetric"] { padding:.8rem; } .st-key-auth-page-shell { min-height:calc(100vh - 2rem); padding:1rem .85rem; } .st-key-auth-form h2 { font-size:1.6rem!important; } }
@media (max-width: 760px) {
  .st-key-tutor-collapsed-header [data-testid="stHorizontalBlock"] { display:grid!important; grid-template-columns:minmax(0,1fr) 2.75rem; align-items:start; gap:.5rem; }
  .st-key-tutor-collapsed-header [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { box-sizing:border-box; width:auto!important; min-width:0!important; flex:none!important; }
  .st-key-tutor-drawer-header [data-testid="stHorizontalBlock"] { display:grid!important; grid-template-columns:minmax(0,1fr) 2.75rem; align-items:start; gap:.5rem; }
  .st-key-tutor-drawer-header [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { box-sizing:border-box; width:auto!important; min-width:0!important; flex:none!important; }
}
@media (max-width: 760px) {
  .st-key-lp-diagnostic-card [data-testid="stHorizontalBlock"] { gap:.85rem; }
  .lp-recommendation-details { grid-template-columns:minmax(0,1fr); }
}
@media (max-width: 1150px) {
  [data-testid="stHorizontalBlock"]:has(.st-key-lp-subject-control),
  .st-key-lp-diagnostic-card [data-testid="stHorizontalBlock"] { display:grid!important; grid-template-columns:minmax(0,1fr) var(--lp-select-control-width); align-items:center; gap:.75rem; }
  [data-testid="stHorizontalBlock"]:has(.st-key-lp-subject-control) > [data-testid="stColumn"],
  .st-key-lp-diagnostic-card [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { width:100%!important; min-width:0!important; flex:none!important; }
}
@media (max-width: 760px) {
  [data-testid="stHorizontalBlock"]:has(.st-key-lp-subject-control),
  .st-key-lp-diagnostic-card [data-testid="stHorizontalBlock"] { grid-template-columns:minmax(0,1fr); }
}
@media (max-width: 1050px) {
  .st-key-lp-overview-grid [data-testid="stHorizontalBlock"],
  .st-key-lp-concept-grid [data-testid="stHorizontalBlock"] { grid-template-columns:repeat(2,minmax(0,1fr)); grid-auto-rows:220px; gap:.75rem; }
  .st-key-lp-overview-grid [data-testid="stColumn"],
  .st-key-lp-concept-grid [data-testid="stColumn"] { width:100%!important; min-width:0!important; flex:initial!important; }
  .st-key-dashboard-stat-grid [data-testid="stHorizontalBlock"],
  .st-key-dashboard-subject-grid [data-testid="stHorizontalBlock"],
  .st-key-dashboard-recommendation-grid [data-testid="stHorizontalBlock"] { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.8rem; }
  .st-key-dashboard-stat-grid [data-testid="stColumn"],
  .st-key-dashboard-subject-grid [data-testid="stColumn"],
  .st-key-dashboard-recommendation-grid [data-testid="stColumn"] { width:100%!important; min-width:0!important; flex:initial!important; }
}
@media (max-width: 600px) {
  .st-key-lp-overview-grid [data-testid="stHorizontalBlock"],
  .st-key-lp-concept-grid [data-testid="stHorizontalBlock"] { grid-template-columns:minmax(0,1fr); grid-auto-rows:220px; }
  .st-key-lp-overview-grid [data-testid="stMetric"],
  .st-key-dashboard-stat-grid [data-testid="stHorizontalBlock"],
  .st-key-dashboard-action-grid [data-testid="stHorizontalBlock"],
  .st-key-dashboard-subject-grid [data-testid="stHorizontalBlock"],
  .st-key-dashboard-recommendation-grid [data-testid="stHorizontalBlock"] { grid-template-columns:minmax(0,1fr); }
  .st-key-dashboard-stat-grid [data-testid="stMetric"],
  .st-key-dashboard-subject-grid [data-testid="stVerticalBlockBorderWrapper"],
  .st-key-dashboard-recommendation-grid [data-testid="stVerticalBlockBorderWrapper"] { min-height:auto; }
  .st-key-dashboard-action-grid div.stButton > button,
  .st-key-dashboard-subject-grid div.stButton > button,
  .st-key-dashboard-recommendation-grid div.stButton > button { width:100%; }
}
</style>
""".replace("/* AL_THEME_TOKENS */", _THEME_CSS)
