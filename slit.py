import streamlit as st
import asyncio
import aiohttp
from pathlib import Path
import shutil
import random
from auto_student import Settings, AssignmentSolver, AssignmentData
# Constants
PLAGIARISM_WARNINGS = [
    "Remember, originality is key to learning. Submitting others' work as your own is plagiarism.",
    "Plagiarism can lead to serious academic penalties, including failing grades or expulsion.",
    "Always cite your sources properly to avoid unintentional plagiarism.",
    "Understanding the material yourself is more valuable than any shortcut.",
    "Building a foundation of ethical academic habits will serve you well beyond this assignment.",
    "Think critically and express your own ideas. That's what education is about!",
    "Using AI to generate entire assignments without understanding is a form of academic dishonesty.",
    "Learning to research and write effectively are skills for life, don't cheat yourself out of them.",
    "Be proud of your own work and effort. It's more rewarding!",
    "When in doubt, ask your instructor about proper citation and academic integrity policies."
]
class ProgressTracker:
    def __init__(self):
        self.reset()
    def reset(self):
        self.total_operations = 0
        self.completed_operations = 0
        self.current_phase = ""
        self.phase_weights = {
            "initialization": 0.1,
            "downloading": 0.4,
            "processing": 0.3,
            "ai_generation": 0.2
        }
        self.phase_progress = {}
    def set_phase(self, phase: str, total_ops: int):
        self.current_phase = phase
        self.phase_progress[phase] = {"completed": 0, "total": total_ops}
    def increment_phase(self, phase: str = None):
        phase = phase or self.current_phase
        if phase in self.phase_progress:
            self.phase_progress[phase]["completed"] += 1
    def get_overall_progress(self) -> float:
        total_weighted_progress = 0.0
        for phase, weight in self.phase_weights.items():
            if phase in self.phase_progress:
                phase_data = self.phase_progress[phase]
                if phase_data["total"] > 0:
                    phase_completion = phase_data["completed"] / phase_data["total"]
                    total_weighted_progress += weight * phase_completion
        return min(total_weighted_progress, 1.0)
# Initialize session state
def init_session_state():
    if 'settings' not in st.session_state:
        st.session_state.settings = None
    if 'solver' not in st.session_state:
        st.session_state.solver = None
    if 'classes' not in st.session_state:
        st.session_state.classes = []
    if 'assignments' not in st.session_state:
        st.session_state.assignments = []
    if 'selected_class' not in st.session_state:
        st.session_state.selected_class = None
    if 'selected_assignment' not in st.session_state:
        st.session_state.selected_assignment = None
    if 'results' not in st.session_state:
        st.session_state.results = {}
    if 'progress_tracker' not in st.session_state:
        st.session_state.progress_tracker = ProgressTracker()
    if 'current_view' not in st.session_state:
        st.session_state.current_view = "loading"
    if 'activity_description' not in st.session_state:
        st.session_state.activity_description = "Initializing..."
    if 'plagiarism_warning' not in st.session_state:
        st.session_state.plagiarism_warning = random.choice(PLAGIARISM_WARNINGS)
    # NEW: Track assignments per class
    if 'class_assignments' not in st.session_state:
        st.session_state.class_assignments = {}
# Activity callback handler
def activity_callback(description: str):
    st.session_state.activity_description = description.replace('_', ' ')
    # Update progress tracking
    if "downloading" in description.lower():
        st.session_state.progress_tracker.increment_phase("downloading")
    elif "processing" in description.lower() or "reading" in description.lower():
        st.session_state.progress_tracker.increment_phase("processing")
    elif "openai" in description.lower() or "generating" in description.lower():
        st.session_state.progress_tracker.increment_phase("ai_generation")
    # Update plagiarism warning randomly
    if random.random() < 0.1:  # 10% chance to update on each callback
        st.session_state.plagiarism_warning = random.choice(PLAGIARISM_WARNINGS)
# Async functions
async def initialize_app():
    try:
        st.session_state.settings = Settings()
        activity_callback("Settings_loaded")
        st.session_state.solver = AssignmentSolver(
            st.session_state.settings,
            activity_callback=activity_callback
        )
        async with st.session_state.solver:
            connected = await st.session_state.solver.test_canvas_connection()
            if connected:
                st.session_state.classes = await get_classes()
                if st.session_state.classes:
                    activity_callback("Fetched_classes")
                    st.session_state.current_view = "main_selection"  # Changed to main_selection
                else:
                    activity_callback("No_classes_found")
            else:
                activity_callback("Canvas_connection_failed")
    except Exception as e:
        activity_callback(f"Initialization_Error_{str(e)}")
async def get_classes():
    """Fetch classes using AssignmentSolver"""
    solver = AssignmentSolver(st.session_state.settings)
    async with solver:
        return await solver.get_classes()
async def get_assignments(class_id):
    """Fetch assignments for a specific class"""
    solver = AssignmentSolver(st.session_state.settings)
    async with solver:
        return await solver.get_assignments(class_id)
async def process_assignment(assignment):
    solver = AssignmentSolver(st.session_state.settings)
    async with solver:
        results = await solver.generate_solution(assignment)
    prompt_file = results.get("prompt_file")
    if prompt_file and Path(prompt_file).exists():
        try:
            with open(prompt_file, "r", encoding="utf-8") as f:  # Fixed typo: encode -> encoding
                results["prompt_content"] = f.read()
        except Exception as e:
            results["prompt_content"] = f"[Error reading prompt file: {e}]"
    else:
        results["prompt_content"] = "[Prompt file not found]"
    return results
# UI Components
def show_loading_view():
    st.title("Auto Student - Enhanced")
    st.subheader(st.session_state.activity_description)
    st.progress(0.0)
    st.spinner("Initializing application...")
# NEW: Combined class and assignment selection view
def show_main_selection_view():
    st.title("Select Class and Assignment")
    
    # Refresh classes button
    if st.button("Refresh Classes"):
        st.session_state.class_assignments = {}  # Clear cached assignments
        st.session_state.assignments = []
        st.session_state.selected_class = None
        st.session_state.selected_assignment = None
        st.session_state.current_view = "loading"
        st.session_state.activity_description = "Refreshing classes..."
        asyncio.run(initialize_app())
        return

    if not st.session_state.classes:
        st.warning("No classes found. Please refresh or check your connection.")
        return

    # Class selection dropdown
    class_names = [c.name for c in st.session_state.classes]
    selected_class_name = st.selectbox(
        "Select a class:", 
        class_names,
        index=class_names.index(st.session_state.selected_class.name) 
            if st.session_state.selected_class else 0
    )
    
    # Find the selected class object
    selected_class = next((c for c in st.session_state.classes 
                         if c.name == selected_class_name), None)
    
    if selected_class:
        # Update selected class if changed
        if st.session_state.selected_class != selected_class:
            st.session_state.selected_class = selected_class
            st.session_state.selected_assignment = None  # Reset assignment selection
            st.session_state.currentview = "loading_assignments"
            st.rerun()
        
        # Fetch assignments if not already cached
        if selected_class.id not in st.session_state.class_assignments:
            st.session_state.current_view = "loading_assignments"
            st.session_state.activity_description = f"Loading assignments for {selected_class.name}..."
            st.rerun()
        
        if st.session_state.current_view == "main_selection":
            assignments = st.session_state.class_assignments.get(selected_class.id, [])

            # Get assignments for selected class
            assignments = st.session_state.class_assignments[selected_class.id]
        
        if not assignments:
            st.warning("No assignments found for this class.")
            return
        
        # Assignment selection dropdown
        assignment_names = [a.name for a in assignments]
        selected_assignment_name = st.selectbox(
            "Select an assignment:", 
            assignment_names,
            index=assignment_names.index(st.session_state.selected_assignment.name) 
                if st.session_state.selected_assignment else 0
        )
        
        # Find the selected assignment object
        selected_assignment = next((a for a in assignments 
                                  if a.name == selected_assignment_name), None)
        
        if selected_assignment:
            st.session_state.selected_assignment = selected_assignment
            
            # Process button
            if st.button("Process Assignment"):
                st.session_state.current_view = "processing"
                st.session_state.progress_tracker.reset()
                # Set up progress tracking phases
                total_downloads = len(st.session_state.selected_assignment.links) + \
                                 len(st.session_state.selected_assignment.youtube_video_ids)
                st.session_state.progress_tracker.set_phase("initialization", 1)
                st.session_state.progress_tracker.set_phase("downloading", total_downloads)
                st.session_state.progress_tracker.set_phase("processing", total_downloads)
                st.session_state.progress_tracker.set_phase("ai_generation", 1)
                asyncio.run(process_selected_assignment())

# NEW: View for loading assignments
def show_loading_assignments_view():
    st.title("Loading Assignments")
    st.write(st.session_state.activity_description)
    st.spinner("Loading...")
    # Fetch assignments and store in session state
    assignments = asyncio.run(get_assignments(st.session_state.selected_class.id))
    st.session_state.class_assignments[st.session_state.selected_class.id] = assignments
    st.session_state.current_view = "main_selection"
    st.rerun()

def show_processing_view():
    st.title(f"Processing: {st.session_state.selected_assignment.name}")
    # Progress bar
    progress = st.session_state.progress_tracker.get_overall_progress()
    st.progress(progress)
    # Status
    st.subheader(st.session_state.activity_description)
    # Plagiarism warning
    st.warning(st.session_state.plagiarism_warning)
    # Cancel button
    if st.button("Cancel Processing", key="cancel_processing"):
        st.session_state.current_view = "main_selection"
        st.rerun()
async def process_selected_assignment():
    st.session_state.results = await process_assignment(
        st.session_state.selected_assignment
    )
    st.session_state.current_view = "results"
    st.rerun()
def show_results_view():
    st.title(f"Results: {st.session_state.selected_assignment.name}")
    if not st.session_state.results:
        st.error("No results generated. Processing may have failed.")
        if st.button("Back to Assignments"):
            st.session_state.current_view = "main_selection"
            st.rerun()
        return
    # Display generated solution
    answer_content = st.session_state.results.get("answer_content", "No content generated")
    st.text_area("Generated Solution:", value=answer_content, height=300, key="answer_text")
    # Action buttons
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("📋 Copy to Clipboard"):
            try:
                import pyperclip
                pyperclip.copy(answer_content)
                st.success("Answer copied to clipboard")
            except Exception as e:
                st.error(f"Couldn't copy to clipboard: {e}. Please copy manually.")
    with col2:
        prompt_content = st.session_state.results.get("prompt_content", "")
        prompt_filename = Path(st.session_state.results.get("prompt_file", "prompt.txt")).name
        st.download_button(
            label = "📄 Download Prompt",
            data = prompt_content,
            file_name = prompt_filename,
            mime="text/plain"
        )
    with col3:
        answer_filename = Path(st.session_state.results.get("answer_file", "answer.md")).name
        st.download_button(
            label = "💾 Download Answer",
            data = answer_content,
            file_name = answer_filename,
            mime="text/markdown"
        )
    if st.button("← Back to Assignments", key="back_from_results"):
        st.session_state.current_view = "main_selection"
        st.rerun()
# Main app
def main():
    init_session_state()
    # View router
    if st.session_state.current_view == "loading":
        show_loading_view()
    elif st.session_state.current_view == "loading_assignments":  # NEW view
        show_loading_assignments_view()
    elif st.session_state.current_view == "main_selection":  # Changed from class_selection
        show_main_selection_view()
    elif st.session_state.current_view == "processing":
        show_processing_view()
    elif st.session_state.current_view == "results":
        show_results_view()
if __name__ == "__main__":
    # Initialize the app on first run
    if not st.session_state.get('initialized'):
        asyncio.run(initialize_app())
        st.session_state.initialized = True
    main()
