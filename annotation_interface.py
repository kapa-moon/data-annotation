import streamlit as st
import pandas as pd
import json
import html
import re

st.set_page_config(page_title="Annotation", layout="wide")


@st.cache_data
def load_data_cached(filepath):
    """Load TSV or CSV data with caching."""
    if filepath.endswith('.tsv'):
        return pd.read_csv(filepath, sep='\t')
    else:
        return pd.read_csv(filepath)


@st.cache_data
def load_uploaded_data(uploaded_file_content, file_extension):
    """Load uploaded file data with caching."""
    import io
    if file_extension == 'csv':
        return pd.read_csv(io.BytesIO(uploaded_file_content))
    else:
        return pd.read_csv(io.BytesIO(uploaded_file_content), sep='\t')


def parse_conversation(convo_json):
    """Parse conversation JSON and return list of messages."""
    if pd.isna(convo_json) or convo_json == "":
        return []
    try:
        if isinstance(convo_json, str):
            messages = json.loads(convo_json)
        else:
            messages = convo_json
        return messages if isinstance(messages, list) else []
    except json.JSONDecodeError:
        st.error("Failed to parse conversation JSON")
        return []


def escape_html(text):
    """Escape HTML special characters to prevent rendering issues."""
    return html.escape(str(text)).replace('\n', '<br>')


def apply_highlights(text, highlights_for_msg):
    """Apply highlights to text by wrapping highlighted portions in mark tags."""
    if not highlights_for_msg:
        return escape_html(text)

    escaped_text = escape_html(text)
    # Sort highlights by start position (reverse order to apply from end to start)
    sorted_highlights = sorted(highlights_for_msg, key=lambda x: x.get('start', 0), reverse=True)

    result = escaped_text
    for hl in sorted_highlights:
        hl_text = escape_html(hl.get('text', ''))
        # Find the text and wrap it
        if hl_text in result:
            # Replace with highlighted version
            highlighted = f"<mark style='background-color: #FFEB3B; color: #000; font-weight: bold; padding: 1px 2px; border-radius: 2px;'>{hl_text}</mark>"
            result = result.replace(hl_text, highlighted, 1)

    return result


def load_data(filepath):
    """Load TSV or CSV data."""
    if filepath.endswith('.tsv'):
        return pd.read_csv(filepath, sep='\t')
    else:
        return pd.read_csv(filepath)


def format_value(value):
    """Format a value for display, handling NaN/empty values."""
    if pd.isna(value) or value == "" or str(value).lower() == 'nan':
        return "<span style='color: #999; font-style: italic;'>N/A</span>"
    return html.escape(str(value))


def get_annotated_indices_fast(metaphor_dict, convo_dict, highlights_dict, df_len):
    """Fast function to get annotated indices using set operations."""
    # Get keys with non-empty values
    metaphor_keys = {k for k, v in metaphor_dict.items() if k < df_len and v and v.strip()}
    convo_keys = {k for k, v in convo_dict.items() if k < df_len and v and v.strip()}
    highlight_keys = {k for k, v in highlights_dict.items() if k < df_len and v and len(v) > 0}
    return sorted(metaphor_keys | convo_keys | highlight_keys)


def main():
    # Initialize session state
    if 'metaphor_annotation' not in st.session_state:
        st.session_state.metaphor_annotation = {}
    if 'convo_annotation' not in st.session_state:
        st.session_state.convo_annotation = {}
    if 'current_idx' not in st.session_state:
        st.session_state.current_idx = 0
    if 'highlights' not in st.session_state:
        st.session_state.highlights = {}  # {original_idx: [{msg_idx, text, start, end}, ...]}
    if 'last_uploaded_hash' not in st.session_state:
        st.session_state.last_uploaded_hash = None

    # Sidebar
    with st.sidebar:
        st.markdown("### Settings")

        # Upload Data - moved to sidebar for cleaner top navigation
        st.markdown("**Upload Data**")
        uploaded_file = st.file_uploader("Choose CSV/TSV", type=['csv', 'tsv'], label_visibility="collapsed", key="sidebar_uploader")

        # Only process if we have a new file (different from what's loaded)
        if uploaded_file is not None:
            file_content = uploaded_file.getvalue()
            file_hash = hash(file_content)

            # Check if this is a new file or different from current
            if not st.session_state.get('using_uploaded', False) or \
               st.session_state.get('last_uploaded_hash') != file_hash:

                try:
                    file_extension = uploaded_file.name.split('.')[-1].lower()
                    uploaded_df = load_uploaded_data(file_content, file_extension)
                    st.session_state.uploaded_df = uploaded_df
                    st.session_state.uploaded_file_buffer = file_content
                    st.session_state.last_uploaded_hash = file_hash
                    st.session_state.using_uploaded = True
                    st.success(f"Loaded {len(uploaded_df)} records!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

        st.markdown("---")

        # Show current data source
        if st.session_state.get('using_uploaded', False):
            st.success("Using uploaded file")
            if st.button("Reset to default"):
                st.session_state.using_uploaded = False
                st.session_state.last_uploaded_hash = None
                if 'uploaded_df' in st.session_state:
                    del st.session_state.uploaded_df
                st.rerun()
        else:
            st.info("Using: annotated_data.csv")

        output_file = st.text_input(
            "Output file",
            value="annotated_data.csv"
        )

    # Check if there's an uploaded file in session state
    if st.session_state.get('using_uploaded', False) and 'uploaded_df' in st.session_state:
        df = st.session_state.uploaded_df
        st.sidebar.success(f"Using uploaded file: {len(df)} records")
    else:
        # Default: load from file path with caching
        default_file = "annotated_data.csv"
        fallback_file = "data.tsv"

        try:
            if pd.io.common.file_exists(default_file):
                df = load_data_cached(default_file)
            elif pd.io.common.file_exists(fallback_file):
                df = load_data_cached(fallback_file)
            else:
                st.error(f"File not found: {default_file} or {fallback_file}. Please upload a file using the 'Upload Data' button.")
                return
        except Exception as e:
            st.error(f"Error loading file: {e}")
            return

    # Load highlights lazily - only for current record when needed
    # Don't load all highlights on startup for large datasets

    # Handle filtering for annotated records only - use fast function
    if st.session_state.get('show_annotated_only', False):
        # Use fast set-based function to get annotated indices (includes highlights)
        annotated_indices = get_annotated_indices_fast(
            st.session_state.metaphor_annotation,
            st.session_state.convo_annotation,
            st.session_state.highlights,
            len(df)
        )

        if len(annotated_indices) == 0:
            st.sidebar.warning("No annotated records found. Showing all.")
            st.session_state.show_annotated_only = False
            filtered_df = df
            index_mapping = list(range(len(df)))
        else:
            filtered_df = df.iloc[annotated_indices].reset_index(drop=True)
            index_mapping = annotated_indices  # Maps filtered index to original index
            st.sidebar.markdown(f"**Showing:** {len(annotated_indices)} annotated of {len(df)} total")
    else:
        filtered_df = df
        index_mapping = list(range(len(df)))

    st.sidebar.markdown(f"**Total Records:** {len(df)}")

    # Ensure index is valid for filtered data
    max_idx = len(filtered_df) - 1
    if st.session_state.current_idx > max_idx:
        st.session_state.current_idx = 0
    if st.session_state.current_idx < 0:
        st.session_state.current_idx = max_idx

    filtered_idx = st.session_state.current_idx
    original_idx = index_mapping[filtered_idx]
    row = filtered_df.iloc[filtered_idx]

    # Lazy load highlights for this specific record only
    if 'conversation_highlights' in df.columns and original_idx not in st.session_state.highlights:
        hl_data = row.get('conversation_highlights', '')
        if pd.notna(hl_data) and hl_data.strip():
            try:
                if isinstance(hl_data, str):
                    st.session_state.highlights[original_idx] = json.loads(hl_data)
            except json.JSONDecodeError:
                pass

    # ROW 1: Navigation (full width) - compact single line
    nav_col1, nav_col2, nav_col3, nav_col4, nav_col5, nav_col6 = st.columns([0.8, 1.5, 0.8, 2, 2.5, 1])

    with nav_col1:
        if st.button("← Previous", use_container_width=True):
            st.session_state.current_idx = max(0, filtered_idx - 1)
            st.rerun()

    with nav_col2:
        # Smaller, unbold record counter - show filtered position
        show_filtered = st.session_state.get('show_annotated_only', False)
        if show_filtered:
            counter_text = f"{filtered_idx + 1} of {len(filtered_df)} annotated"
        else:
            counter_text = f"{filtered_idx + 1} of {len(filtered_df)}"
        st.markdown(f"<p style='text-align: center; margin: 0; color: black; font-size: 0.9em; font-weight: normal; padding-top: 6px;'>{counter_text}</p>", unsafe_allow_html=True)

    with nav_col3:
        if st.button("Next →", use_container_width=True):
            st.session_state.current_idx = min(len(filtered_df) - 1, filtered_idx + 1)
            st.rerun()

    with nav_col4:
        # Search by ResponseId - compact
        search_id = st.text_input("Search", value="", placeholder="Search ID", label_visibility="collapsed")
        if search_id and 'ResponseId' in df.columns:
            matching = df[df['ResponseId'] == search_id]
            if len(matching) > 0:
                found_original_idx = matching.index[0]
                if found_original_idx in index_mapping:
                    st.session_state.current_idx = index_mapping.index(found_original_idx)
                    st.rerun()
                else:
                    st.sidebar.warning("Not in filtered list")

    with nav_col5:
        # Filter button - compact
        if 'show_annotated_only' not in st.session_state:
            st.session_state.show_annotated_only = False

        btn_label = "Show all" if st.session_state.show_annotated_only else "Annotated only"
        if st.button(btn_label, key="filter_annotated_btn", use_container_width=True):
            st.session_state.show_annotated_only = not st.session_state.show_annotated_only
            st.rerun()

    with nav_col6:
        # Export button in the same row
        export_clicked = st.button("💾 Export to CSV", type="primary")

    # Handle export outside of column context to avoid layout issues
    if export_clicked:
        with st.spinner("Saving..."):
            export_df = df.copy()
            export_df['metaphor_annotate'] = ""
            export_df['convo_history_annotate'] = ""
            export_df['conversation_highlights'] = ""

            for idx, annotation in st.session_state.metaphor_annotation.items():
                if idx < len(export_df):
                    export_df.at[idx, 'metaphor_annotate'] = annotation

            for idx, annotation in st.session_state.convo_annotation.items():
                if idx < len(export_df):
                    export_df.at[idx, 'convo_history_annotate'] = annotation

            for idx, highlights in st.session_state.highlights.items():
                if idx < len(export_df):
                    export_df.at[idx, 'conversation_highlights'] = json.dumps(highlights)

            export_df.to_csv(output_file, index=False)
        st.toast(f"Saved to {output_file}!", icon="✅")

    st.markdown("---")

    # ROW 2: Metadata (full width)
    meta_header_col1, meta_header_col2, meta_header_col3 = st.columns([5, 3, 1.2])

    with meta_header_col1:
        st.markdown("**Metadata**")

    with meta_header_col2:
        pass  # Spacer to push button to the right

    with meta_header_col3:
        # Toggle button for showing/hiding labeled condition and user intention
        if 'show_colored_fields' not in st.session_state:
            st.session_state.show_colored_fields = True

        toggle_label = "Hide" if st.session_state.show_colored_fields else "Show"
        if st.button(f"{toggle_label} Labels", key="toggle_labels_btn"):
            st.session_state.show_colored_fields = not st.session_state.show_colored_fields
            st.rerun()

    # Color coding functions
    def get_intention_color(value):
        """Get color for Intention field."""
        if pd.isna(value):
            return "#737373"
        val = str(value).lower()
        if "emotional support" in val or "validation" in val or "reassurance" in val:
            return "#fc743a"  # Orange
        elif "information" in val or "practical" in val or "actionable" in val or "guidance" in val:
            return "#297eff"  # Blue
        else:
            return "#737373"  # Gray

    def get_label_condition_color(value):
        """Get color for Label Condition field."""
        if pd.isna(value):
            return "#737373"
        val = str(value).lower()
        if "labeled" in val:
            return "#21802e"  # Green
        else:
            return "#ed427b"  # Pink/Red

    def render_color_box(content, color, is_html=False):
        """Render content in a styled box with border and background."""
        if is_html:
            # For HTML content, preserve the HTML tags
            return f"""
            <div style='
                border: 2px solid {color};
                border-radius: 12px;
                background-color: {color}15;
                padding: 10px 14px;
                margin: 4px 0;
                font-size: 0.85em;
            '>
                {content}
            </div>
            """
        else:
            escaped = escape_html(content)
            return f"""
            <div style='
                border: 2px solid {color};
                border-radius: 12px;
                background-color: {color}15;
                padding: 10px 14px;
                margin: 4px 0;
                font-size: 0.85em;
            '>
                {escaped}
            </div>
            """

    meta_cols = st.columns(4)

    with meta_cols[0]:
        # ResponseId
        if 'ResponseId' in filtered_df.columns:
            value = format_value(row.get('ResponseId', 'N/A'))
            st.markdown(f"<small><b>ResponseId:</b> {value}</small>", unsafe_allow_html=True)

    with meta_cols[1]:
        # ID
        if 'id' in filtered_df.columns:
            value = format_value(row.get('id', 'N/A'))
            st.markdown(f"<small><b>ID:</b> {value}</small>", unsafe_allow_html=True)

    # Only show Intention and Label Condition if toggle is on
    show_colored = st.session_state.get('show_colored_fields', True)

    with meta_cols[2]:
        if show_colored:
            # Intention with color coding
            if 'Q155' in filtered_df.columns:
                intention_val = row.get('Q155', '')
                intention_color = get_intention_color(intention_val)
                st.markdown("<small><b>Intention:</b></small>", unsafe_allow_html=True)
                if pd.isna(intention_val) or intention_val == '':
                    st.markdown(render_color_box("N/A", "#737373"), unsafe_allow_html=True)
                else:
                    st.markdown(render_color_box(str(intention_val), intention_color), unsafe_allow_html=True)

            # Intention (Other)
            if 'Q155_6_TEXT' in filtered_df.columns:
                other_val = row.get('Q155_6_TEXT', '')
                if not pd.isna(other_val) and str(other_val).strip():
                    st.markdown("<small><i>Other:</i></small>", unsafe_allow_html=True)
                    st.markdown(f"<small>{format_value(other_val)}</small>", unsafe_allow_html=True)

    with meta_cols[3]:
        if show_colored:
            # Label Condition with color coding
            if 'label_condition' in filtered_df.columns:
                label_val = row.get('label_condition', '')
                label_color = get_label_condition_color(label_val)
                st.markdown("<small><b>Label Condition:</b></small>", unsafe_allow_html=True)
                if pd.isna(label_val) or label_val == '':
                    st.markdown(render_color_box("N/A", "#737373"), unsafe_allow_html=True)
                else:
                    st.markdown(render_color_box(str(label_val), label_color), unsafe_allow_html=True)

    # Second row for longer fields
    meta_cols2 = st.columns([1, 1])

    with meta_cols2[0]:
        # Picked Scenario - render as HTML without color box
        if 'pickedScenario' in filtered_df.columns:
            scenario_val = row.get('pickedScenario', '')
            st.markdown("<small><b>Picked Scenario:</b></small>", unsafe_allow_html=True)
            if pd.isna(scenario_val) or scenario_val == '':
                st.markdown("<small><i>N/A</i></small>", unsafe_allow_html=True)
            else:
                # Render HTML content directly
                st.markdown(f"<small>{scenario_val}</small>", unsafe_allow_html=True)

    with meta_cols2[1]:
        # Participant Text Response
        if 'participantTextResponse' in filtered_df.columns:
            text_val = row.get('participantTextResponse', '')
            st.markdown("<small><b>Participant Text:</b></small>", unsafe_allow_html=True)
            if pd.isna(text_val) or text_val == '':
                st.markdown("<small><i>N/A</i></small>", unsafe_allow_html=True)
            else:
                escaped = escape_html(str(text_val))
                st.markdown(f"<small>{escaped}</small>", unsafe_allow_html=True)

        # Specific Label
        if 'specific_label' in filtered_df.columns:
            label_val = row.get('specific_label', '')
            if not pd.isna(label_val) and str(label_val).strip():
                st.markdown(f"<small><b>Specific Label:</b> {format_value(label_val)}</small>", unsafe_allow_html=True)

    st.markdown("---")

    # ROW 3: Metaphor Annotation (65% / 35% split)
    metaphor_data_col, metaphor_note_col = st.columns([0.65, 0.35])

    with metaphor_data_col:
        st.markdown("**Metaphor**")
        meta_col1, meta_col2 = st.columns([1, 1])

        with meta_col1:
            st.markdown("*AI Metaphor:*")
            ai_metaphor = format_value(row.get('ai_metaphor', 'N/A'))
            st.markdown(f"<div style='background-color: #f5f5f5; padding: 10px; border-radius: 5px; font-size: 0.9em;'>{ai_metaphor}</div>", unsafe_allow_html=True)

        with meta_col2:
            st.markdown("*Metaphor Rationale:*")
            metaphor_rationale = format_value(row.get('metaphor_rationale', 'N/A'))
            st.markdown(f"<div style='background-color: #f5f5f5; padding: 10px; border-radius: 5px; font-size: 0.9em;'>{metaphor_rationale}</div>", unsafe_allow_html=True)

    with metaphor_note_col:
        st.markdown("**Your Annotation**")
        default_metaphor = st.session_state.metaphor_annotation.get(original_idx, "")
        metaphor_annotation = st.text_area(
            "Metaphor annotation",
            value=default_metaphor,
            height=200,
            key=f"metaphor_input_{original_idx}",
            placeholder="Enter annotation...",
            label_visibility="collapsed"
        )
        st.session_state.metaphor_annotation[original_idx] = metaphor_annotation

        btn_col1, btn_col2 = st.columns([1, 1])
        with btn_col1:
            if st.button("Save", key=f"save_met_btn_{original_idx}"):
                st.toast("Saved!", icon="✅")
        with btn_col2:
            if st.button("Clear", key=f"clear_met_btn_{original_idx}"):
                st.session_state.metaphor_annotation[original_idx] = ""
                st.rerun()

    st.markdown("---")

    # ROW 4: Conversation History (65% / 35% split)
    convo_data_col, convo_note_col = st.columns([0.65, 0.35])

    with convo_data_col:
        st.markdown("**Conversation History**")

        # Initialize active highlight message if not exists
        if 'active_highlight_msg' not in st.session_state:
            st.session_state.active_highlight_msg = None

        if 'convo_history' in filtered_df.columns:
            convo_data = row.get('convo_history', '')
            messages = parse_conversation(convo_data)

            # Get highlights for this record
            record_highlights = st.session_state.highlights.get(original_idx, [])

            # Build display message list (excluding system)
            display_messages = []
            for msg_idx, msg in enumerate(messages):
                if msg.get('role') != 'system':
                    display_messages.append((msg_idx, msg))

            if messages:
                # Scrollable container with max height of viewport
                chat_container = st.container(height=600, border=True)
                with chat_container:
                    for display_idx, (msg_idx, msg) in enumerate(display_messages):
                        role = msg.get('role', '')
                        content = msg.get('content', '')

                        # Get highlights for this message
                        msg_highlights = [hl for hl in record_highlights if hl.get('msg_idx') == msg_idx]

                        # Apply highlights to the content
                        if msg_highlights:
                            displayed_content = apply_highlights(content, msg_highlights)
                        else:
                            displayed_content = escape_html(content)

                        # Display message with integrated highlight button
                        if role == 'user':
                            cols = st.columns([1, 3])
                            with cols[1]:
                                # Message bubble
                                st.markdown(
                                    f"<div style='background-color: #DCF8C6; border-radius: 12px 12px 12px 4px; padding: 8px 12px; margin: 4px 0; font-size: 0.85em;'>"
                                    f"<div style='font-size: 0.7em; color: #2E7D32; margin-bottom: 2px;'><b>User</b></div>"
                                    f"<div style='color: #000;'>{displayed_content}</div>"
                                    f"</div>",
                                    unsafe_allow_html=True
                                )
                                # Add highlight link inside the bubble area
                                if st.session_state.active_highlight_msg != msg_idx:
                                    if st.button("Add highlight", key=f"hl_toggle_{original_idx}_{msg_idx}", 
                                                type="tertiary", use_container_width=False):
                                        st.session_state.active_highlight_msg = msg_idx
                                        st.rerun()
                        else:
                            cols = st.columns([3, 1])
                            with cols[0]:
                                # Message bubble
                                st.markdown(
                                    f"<div style='background-color: #FFFFFF; border: 1px solid #E0E0E0; border-radius: 12px 12px 4px 12px; padding: 8px 12px; margin: 4px 0; font-size: 0.85em;'>"
                                    f"<div style='font-size: 0.7em; color: #666; margin-bottom: 2px;'><b>AI</b></div>"
                                    f"<div style='color: #000;'>{displayed_content}</div>"
                                    f"</div>",
                                    unsafe_allow_html=True
                                )
                                # Add highlight link inside the bubble area
                                if st.session_state.active_highlight_msg != msg_idx:
                                    if st.button("Add highlight", key=f"hl_toggle_{original_idx}_{msg_idx}",
                                                type="tertiary", use_container_width=False):
                                        st.session_state.active_highlight_msg = msg_idx
                                        st.rerun()

                        # Show highlight input if this message is active
                        if st.session_state.active_highlight_msg == msg_idx:
                            st.markdown("<div style='margin-left: 20px; margin-top: -8px;'>", unsafe_allow_html=True)
                            hl_cols = st.columns([3, 0.8, 0.5])
                            with hl_cols[0]:
                                hl_text = st.text_input(
                                    "Text to highlight",
                                    key=f"hl_input_{original_idx}_{msg_idx}",
                                    placeholder="Type exact text from message...",
                                    label_visibility="collapsed"
                                )
                            with hl_cols[1]:
                                if st.button("Add", key=f"hl_btn_{original_idx}_{msg_idx}"):
                                    if hl_text.strip():
                                        if hl_text in content:
                                            start_pos = content.index(hl_text)
                                            if original_idx not in st.session_state.highlights:
                                                st.session_state.highlights[original_idx] = []
                                            st.session_state.highlights[original_idx].append({
                                                'msg_idx': msg_idx,
                                                'text': hl_text,
                                                'start': start_pos,
                                                'end': start_pos + len(hl_text)
                                            })
                                            st.session_state.active_highlight_msg = None
                                            st.rerun()
                                        else:
                                            st.error("Text not found")
                            with hl_cols[2]:
                                if st.button("Cancel", key=f"hl_cancel_{original_idx}_{msg_idx}"):
                                    st.session_state.active_highlight_msg = None
                                    st.rerun()
                            st.markdown("</div>", unsafe_allow_html=True)
            else:
                st.info("No conversation history available.")
        else:
            st.warning("Conversation history column not found.")

    with convo_note_col:
        st.markdown("**Your Annotation**")
        default_convo = st.session_state.convo_annotation.get(original_idx, "")
        convo_annotation = st.text_area(
            "Conversation annotation",
            value=default_convo,
            height=200,
            key=f"convo_input_{original_idx}",
            placeholder="Enter annotation...",
            label_visibility="collapsed"
        )
        st.session_state.convo_annotation[original_idx] = convo_annotation

        btn_col1, btn_col2 = st.columns([1, 1])
        with btn_col1:
            if st.button("Save", key=f"save_convo_btn_{original_idx}"):
                st.toast("Saved!", icon="✅")
        with btn_col2:
            if st.button("Clear", key=f"clear_convo_btn_{original_idx}"):
                st.session_state.convo_annotation[original_idx] = ""
                st.rerun()

        # Show current highlights summary
        record_highlights = st.session_state.highlights.get(original_idx, [])

        # Build display message list for mapping msg_idx to role
        if 'convo_history' in filtered_df.columns:
            convo_data = row.get('convo_history', '')
            messages = parse_conversation(convo_data)
            msg_role_map = {}
            for msg_idx, msg in enumerate(messages):
                if msg.get('role') != 'system':
                    msg_role_map[msg_idx] = msg.get('role', '')
        else:
            msg_role_map = {}

        if record_highlights:
            st.markdown("---")
            st.markdown(f"<small><i>{len(record_highlights)} highlight(s):</i></small>", unsafe_allow_html=True)

            # Scrollable list of highlights
            highlights_container = st.container(height=150, border=False)
            with highlights_container:
                for i, hl in enumerate(record_highlights):
                    msg_idx = hl.get('msg_idx', 0)
                    role = msg_role_map.get(msg_idx, '')
                    hl_text = hl.get('text', '')

                    # Determine label and color based on role
                    if role == 'user':
                        label = "User"
                        bg_color = "#DCF8C6"  # Green for user
                    else:
                        label = "AI"
                        bg_color = "#FFFFFF"  # White for AI

                    # Create a compact highlight entry
                    st.markdown(
                        f"<div style='background-color: {bg_color}; border: 1px solid #ddd; border-radius: 6px; padding: 6px 8px; margin: 4px 0; font-size: 0.75em;'>"
                        f"<div style='font-size: 0.7em; color: #666; margin-bottom: 2px;'><b>{label}</b></div>"
                        f"<mark style='background-color: #FFEB3B; color: #000; font-weight: bold; padding: 1px 3px; border-radius: 2px;'>{escape_html(hl_text)}</mark>"
                        f"</div>",
                        unsafe_allow_html=True
                    )


if __name__ == "__main__":
    main()
