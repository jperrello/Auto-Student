import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
import asyncio
import threading
import random
import shutil
from pathlib import Path
from typing import Dict, List, Optional, Any
import aiohttp  # CRITICAL: You forgot this import!
from auto_student import *

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

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

class ProgressTracker:
    """Proper progress tracking instead of your broken heuristic approach"""
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

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Auto Student GUI - Enhanced")
        self.geometry("900x800")
        self.minsize(800, 600)

        # State management
        self.settings: Optional[Settings] = None
        self.solver: Optional[AssignmentSolver] = None
        self.assignments: List[AssignmentData] = []
        self.current_assignment: Optional[AssignmentData] = None
        self.results: Dict[str, Any] = {}
        
        # Progress tracking
        self.progress_tracker = ProgressTracker()
        
        # Asyncio setup with proper error handling
        self.setup_async_loop()
        
        # UI Setup
        self.setup_ui()
        self.bind_events()
        
        # Initialize
        self.initialize_app()

    def setup_async_loop(self):
        """Properly setup async loop with error handling"""
        try:
            self.loop = asyncio.new_event_loop()
            self.thread = threading.Thread(target=self._run_async_loop, daemon=True)
            self.thread.start()
        except Exception as e:
            messagebox.showerror("Initialization Error", f"Failed to setup async loop: {e}")
            self.destroy()

    def _run_async_loop(self):
        """Run async loop with proper exception handling"""
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        except Exception as e:
            print(f"Async loop error: {e}")
        finally:
            try:
                # Cancel all pending tasks
                pending = asyncio.all_tasks(self.loop)
                for task in pending:
                    task.cancel()
                if pending:
                    self.loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception:
                pass
            finally:
                self.loop.close()

    def setup_ui(self):
        """Create UI with better organization and menu"""
        # Menu bar
        self.create_menu()
        
        # Main container
        self.container = ctk.CTkFrame(self)
        self.container.pack(side="top", fill="both", expand=True, padx=10, pady=10)
        
        # Create frames
        self.frames: Dict[str, ctk.CTkFrame] = {}
        self.create_frames()
        
        # Configure grid
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

    def create_menu(self):
        """Add a proper menu bar"""
        menubar = tk.Menu(self)
        self.config(menu=menubar)
        
        # File menu
        file_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="File", menu=file_menu)
        file_menu.add_command(label="Refresh Assignments", command=self.refresh_assignments)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.on_closing)
        
        # Edit menu
        edit_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Edit", menu=edit_menu)
        edit_menu.add_command(label="Copy Answer to Clipboard", command=self.copy_to_clipboard)
        edit_menu.add_command(label="Clear Downloads", command=self.clear_downloads)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="About", command=self.show_about)

    def create_frames(self):
        """Create all UI frames with better layouts"""
        # Loading Frame
        self.create_loading_frame()
        
        # Assignment List Frame  
        self.create_assignment_list_frame()
        
        # Processing Frame
        self.create_processing_frame()
        
        # Results Frame
        self.create_results_frame()

    def create_loading_frame(self):
        frame = ctk.CTkFrame(self.container)
        self.frames["loading"] = frame
        
        # Center content
        center_frame = ctk.CTkFrame(frame)
        center_frame.pack(expand=True, fill="both")
        
        self.loading_label = ctk.CTkLabel(
            center_frame, 
            text="Initializing...", 
            font=ctk.CTkFont(size=18)
        )
        self.loading_label.pack(pady=20, expand=True)
        
        # Loading spinner (you could add an actual spinner here)
        self.loading_progress = ctk.CTkProgressBar(center_frame, mode="indeterminate")
        self.loading_progress.pack(pady=10, padx=50, fill="x")
        self.loading_progress.start()
        
        frame.grid(row=0, column=0, sticky="nsew")

    def create_assignment_list_frame(self):
        frame = ctk.CTkFrame(self.container)
        self.frames["assignment_list"] = frame
        
        # Header
        header_frame = ctk.CTkFrame(frame)
        header_frame.pack(fill="x", padx=10, pady=10)
        
        title_label = ctk.CTkLabel(
            header_frame, 
            text="Available Assignments", 
            font=ctk.CTkFont(size=20, weight="bold")
        )
        title_label.pack(side="left", pady=10)
        
        refresh_btn = ctk.CTkButton(
            header_frame, 
            text="Refresh", 
            command=self.refresh_assignments,
            width=100
        )
        refresh_btn.pack(side="right", pady=10, padx=10)
        
        # Assignment list
        self.assignment_scrollable = ctk.CTkScrollableFrame(frame)
        self.assignment_scrollable.pack(pady=10, padx=10, fill="both", expand=True)
        
        frame.grid(row=0, column=0, sticky="nsew")

    def create_processing_frame(self):
        frame = ctk.CTkFrame(self.container)
        self.frames["processing"] = frame
        
        # Assignment info
        self.proc_assignment_label = ctk.CTkLabel(
            frame, 
            text="", 
            font=ctk.CTkFont(size=16, weight="bold"),
            wraplength=800
        )
        self.proc_assignment_label.pack(pady=10, padx=10)
        
        # Progress section
        progress_frame = ctk.CTkFrame(frame)
        progress_frame.pack(fill="x", padx=20, pady=10)
        
        ctk.CTkLabel(
            progress_frame, 
            text="Progress:", 
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10,5))
        
        self.proc_progressbar = ctk.CTkProgressBar(progress_frame, mode="determinate")
        self.proc_progressbar.set(0)
        self.proc_progressbar.pack(pady=(0,10), padx=10, fill="x")
        
        self.proc_status_label = ctk.CTkLabel(
            progress_frame, 
            text="Starting...", 
            font=ctk.CTkFont(size=12)
        )
        self.proc_status_label.pack(anchor="w", padx=10, pady=(0,10))
        
        # Plagiarism warning
        warning_frame = ctk.CTkFrame(frame)
        warning_frame.pack(fill="x", padx=20, pady=10)
        
        ctk.CTkLabel(
            warning_frame,
            text="⚠️ Academic Integrity Reminder",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=("orange", "orange")
        ).pack(pady=(10,5))
        
        self.proc_plagiarism_label = ctk.CTkLabel(
            warning_frame, 
            text="", 
            wraplength=700, 
            justify=tk.CENTER, 
            font=ctk.CTkFont(size=11, slant="italic")
        )
        self.proc_plagiarism_label.pack(pady=(0,10), padx=10)
        
        # Cancel button
        self.cancel_btn = ctk.CTkButton(
            frame, 
            text="Cancel Processing", 
            command=self.cancel_processing,
            fg_color="red",
            hover_color="darkred"
        )
        self.cancel_btn.pack(pady=20)
        
        frame.grid(row=0, column=0, sticky="nsew")

    def create_results_frame(self):
        frame = ctk.CTkFrame(self.container)
        self.frames["results"] = frame
        
        # Header with assignment name
        header_frame = ctk.CTkFrame(frame)
        header_frame.pack(fill="x", padx=10, pady=10)
        
        self.res_assignment_label = ctk.CTkLabel(
            header_frame, 
            text="", 
            font=ctk.CTkFont(size=16, weight="bold"),
            wraplength=800
        )
        self.res_assignment_label.pack(pady=10)
        
        # Answer display
        answer_frame = ctk.CTkFrame(frame)
        answer_frame.pack(fill="both", expand=True, padx=10, pady=(0,10))
        
        ctk.CTkLabel(
            answer_frame, 
            text="Generated Solution:", 
            font=ctk.CTkFont(size=14, weight="bold")
        ).pack(anchor="w", padx=10, pady=(10,5))
        
        self.res_textbox = ctk.CTkTextbox(
            answer_frame, 
            wrap="word", 
            font=ctk.CTkFont(size=12)
        )
        self.res_textbox.pack(pady=(0,10), padx=10, fill="both", expand=True)
        
        # Button frame
        btn_frame = ctk.CTkFrame(frame)
        btn_frame.pack(fill="x", padx=10, pady=(0,10))
        
        # Left side buttons
        left_btn_frame = ctk.CTkFrame(btn_frame)
        left_btn_frame.pack(side="left", padx=10, pady=10)
        
        self.copy_btn = ctk.CTkButton(
            left_btn_frame, 
            text="📋 Copy to Clipboard", 
            command=self.copy_to_clipboard,
            width=150
        )
        self.copy_btn.pack(side="left", padx=5)
        
        self.download_prompt_btn = ctk.CTkButton(
            left_btn_frame, 
            text="📄 Download Prompt", 
            command=self.download_prompt,
            width=150
        )
        self.download_prompt_btn.pack(side="left", padx=5)
        
        self.download_answer_btn = ctk.CTkButton(
            left_btn_frame, 
            text="💾 Download Answer", 
            command=self.download_answer,
            width=150
        )
        self.download_answer_btn.pack(side="left", padx=5)
        
        # Right side button
        self.back_btn = ctk.CTkButton(
            btn_frame, 
            text="← Back to Assignments", 
            command=lambda: self.show_frame("assignment_list"),
            width=150
        )
        self.back_btn.pack(side="right", padx=10, pady=10)
        
        frame.grid(row=0, column=0, sticky="nsew")

    def bind_events(self):
        """Bind keyboard shortcuts and events"""
        self.bind("<Control-c>", lambda e: self.copy_to_clipboard())
        self.bind("<Control-r>", lambda e: self.refresh_assignments())
        self.bind("<F5>", lambda e: self.refresh_assignments())

    def show_frame(self, frame_name: str):
        """Show specified frame"""
        if frame_name in self.frames:
            self.frames[frame_name].tkraise()

    def schedule_async_task(self, coro):
        """Schedule async task with proper error handling"""
        try:
            if self.loop and not self.loop.is_closed():
                future = asyncio.run_coroutine_threadsafe(coro, self.loop)
                return future
        except Exception as e:
            print(f"Error scheduling async task: {e}")
            self.after(0, lambda: messagebox.showerror("Error", f"Failed to schedule task: {e}"))
        return None

    def activity_callback(self, description: str):
        """Handle activity updates with proper progress tracking"""
        self.after(0, self.update_gui_on_activity, description)

    def update_gui_on_activity(self, description: str):
        """Update GUI based on activity with proper progress calculation"""
        clean_desc = description.replace('_', ' ')
        
        # Update progress tracking
        if "downloading" in description.lower():
            self.progress_tracker.increment_phase("downloading")
        elif "processing" in description.lower() or "reading" in description.lower():
            self.progress_tracker.increment_phase("processing")
        elif "openai" in description.lower() or "generating" in description.lower():
            self.progress_tracker.increment_phase("ai_generation")
        
        # Update progress bar
        progress = self.progress_tracker.get_overall_progress()
        self.proc_progressbar.set(progress)
        
        # Update status
        self.proc_status_label.configure(text=f"Current: {clean_desc}")
        
        # Update plagiarism warning
        self.proc_plagiarism_label.configure(text=random.choice(PLAGIARISM_WARNINGS))
        
        # Handle specific states
        if "Canvas_connection_successful" in description:
            self.loading_label.configure(text="Canvas Connected! Fetching assignments...")
        elif "Fetched_" in description and "_assignments" in description:
            self.loading_label.configure(text="Assignments loaded successfully!")
            self.loading_progress.stop()
            self.populate_assignment_list()
            self.show_frame("assignment_list")
        elif "failed" in description.lower() or "error" in description.lower():
            self.loading_progress.stop()
            self.loading_label.configure(text=f"Error: {clean_desc}")
            messagebox.showerror("Error", f"Operation failed: {clean_desc}")

    def initialize_app(self):
        """Initialize the application"""
        self.show_frame("loading")
        self.loading_label.configure(text="Loading settings...")
        
        async def async_init():
            try:
                # Load settings
                self.settings = Settings()
                self.activity_callback("Settings_loaded")
                
                # Create solver with proper session management
                self.solver = AssignmentSolver(self.settings, activity_callback=self.activity_callback)
                
                # Test connection and fetch assignments
                async with self.solver:  # This properly manages the aiohttp session
                    connected = await self.solver.test_canvas_connection()
                    if connected:
                        self.assignments = await self.solver.fetch_all_assignments()
                        if not self.assignments:
                            self.activity_callback("No_assignments_found")
                            self.after(0, lambda: messagebox.showinfo("Info", "No assignments found."))
                    else:
                        self.after(0, lambda: messagebox.showerror("Error", "Failed to connect to Canvas."))
                        
            except Exception as e:
                self.activity_callback(f"Initialization_Error_{str(e)}")
                self.after(0, lambda: messagebox.showerror("Error", f"Initialization failed: {e}"))
        
        self.schedule_async_task(async_init())

    def populate_assignment_list(self):
        """Populate the assignment list with improved UI"""
        # Clear existing widgets
        for widget in self.assignment_scrollable.winfo_children():
            widget.destroy()

        if not self.assignments:
            no_assign_label = ctk.CTkLabel(
                self.assignment_scrollable, 
                text="No assignments found.",
                font=ctk.CTkFont(size=14)
            )
            no_assign_label.pack(pady=20)
            return

        for i, assignment in enumerate(self.assignments):
            # Create assignment frame
            assign_frame = ctk.CTkFrame(self.assignment_scrollable)
            assign_frame.pack(pady=5, padx=10, fill="x")
            
            # Assignment info
            info_text = f"{i + 1}. {assignment.name}"
            if assignment.links or assignment.youtube_video_ids:
                info_text += f" ({len(assignment.links)} links, {len(assignment.youtube_video_ids)} videos)"
            
            assign_label = ctk.CTkLabel(
                assign_frame, 
                text=info_text, 
                font=ctk.CTkFont(size=12),
                wraplength=600,
                justify="left"
            )
            assign_label.pack(side="left", padx=10, pady=10, fill="x", expand=True)
            
            # Process button
            process_btn = ctk.CTkButton(
                assign_frame, 
                text="Process", 
                command=lambda a=assignment: self.start_assignment_processing(a),
                width=100
            )
            process_btn.pack(side="right", padx=10, pady=10)

    def start_assignment_processing(self, assignment: AssignmentData):
        """Start processing assignment with proper progress tracking"""
        self.current_assignment = assignment
        self.progress_tracker.reset()
        
        # Set up progress tracking phases
        total_downloads = len(assignment.links) + len(assignment.youtube_video_ids)
        self.progress_tracker.set_phase("initialization", 1)
        self.progress_tracker.set_phase("downloading", total_downloads)
        self.progress_tracker.set_phase("processing", total_downloads)
        self.progress_tracker.set_phase("ai_generation", 1)
        
        # Update UI
        self.proc_assignment_label.configure(
            text=f"Processing: {assignment.name}\n"
                 f"Description: {len(assignment.description)} chars | "
                 f"Links: {len(assignment.links)} | "
                 f"Videos: {len(assignment.youtube_video_ids)}"
        )
        
        self.proc_progressbar.set(0)
        self.proc_status_label.configure(text="Initializing...")
        self.proc_plagiarism_label.configure(text=random.choice(PLAGIARISM_WARNINGS))
        
        self.show_frame("processing")
        
        async def async_process():
            try:
                # Create new solver instance with session for this task
                solver = AssignmentSolver(self.settings, activity_callback=self.activity_callback)
                
                async with solver:  # Proper session management
                    self.results = await solver.generate_solution(assignment)
                    
                self.after(0, self.show_results)
                
            except Exception as e:
                error_msg = f"Processing failed: {str(e)}"
                self.after(0, lambda: messagebox.showerror("Processing Error", error_msg))
                self.after(0, lambda: self.show_frame("assignment_list"))
        
        self.schedule_async_task(async_process())

    def show_results(self):
        """Display results with improved UI"""
        if not self.results or not self.current_assignment:
            messagebox.showerror("Error", "No results to display")
            return
            
        # Update assignment label
        self.res_assignment_label.configure(
            text=f"Solution for: {self.current_assignment.name}"
        )
        
        # Display answer
        self.res_textbox.delete("1.0", tk.END)
        answer_content = self.results.get("answer_content", "[No content generated]")
        self.res_textbox.insert("1.0", answer_content)
        
        # Enable/disable download buttons
        prompt_exists = self.results.get("prompt_file") and Path(self.results["prompt_file"]).exists()
        answer_exists = self.results.get("answer_file") and Path(self.results["answer_file"]).exists()
        
        self.download_prompt_btn.configure(state="normal" if prompt_exists else "disabled")
        self.download_answer_btn.configure(state="normal" if answer_exists else "disabled")
        
        self.show_frame("results")

    def copy_to_clipboard(self):
        """Copy answer to clipboard with error handling"""
        try:
            if hasattr(self, 'res_textbox'):
                content = self.res_textbox.get("1.0", tk.END).strip()
                if content:
                    self.clipboard_clear()
                    self.clipboard_append(content)
                    self.update()  # Ensure clipboard is updated
                    messagebox.showinfo("Success", "Answer copied to clipboard!")
                else:
                    messagebox.showwarning("Warning", "No content to copy.")
            else:
                messagebox.showwarning("Warning", "No answer available to copy.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to copy to clipboard: {e}")

    def download_file_helper(self, source_path: Optional[str], title: str, extension: str):
        """Helper method for file downloads with proper error handling"""
        if not source_path or not Path(source_path).exists():
            messagebox.showerror("Error", "File not found or not generated.")
            return
        
        try:
            source = Path(source_path)
            save_path = filedialog.asksaveasfilename(
                title=title,
                initialfile=source.name,
                defaultextension=extension,
                filetypes=[
                    (f"{extension.upper()} files", f"*{extension}"),
                    ("All files", "*.*")
                ]
            )
            
            if save_path:
                shutil.copy2(source, save_path)
                messagebox.showinfo("Success", f"File saved to: {save_path}")
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save file: {e}")

    def download_prompt(self):
        """Download prompt file"""
        prompt_file = self.results.get("prompt_file") if self.results else None
        self.download_file_helper(prompt_file, "Save Prompt As", ".txt")

    def download_answer(self):
        """Download answer file"""
        answer_file = self.results.get("answer_file") if self.results else None
        self.download_file_helper(answer_file, "Save Answer As", ".md")

    def refresh_assignments(self):
        """Refresh assignment list"""
        if not self.solver:
            messagebox.showwarning("Warning", "Application not initialized.")
            return
            
        self.show_frame("loading")
        self.loading_label.configure(text="Refreshing assignments...")
        self.loading_progress.start()
        
        async def async_refresh():
            try:
                async with self.solver:
                    self.assignments = await self.solver.fetch_all_assignments()
                    self.after(0, self.populate_assignment_list)
                    self.after(0, lambda: self.show_frame("assignment_list"))
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", f"Refresh failed: {e}"))
            finally:
                self.after(0, lambda: self.loading_progress.stop())
        
        self.schedule_async_task(async_refresh())

    def cancel_processing(self):
        """Cancel current processing"""
        # This is complex to implement properly - would need task cancellation
        messagebox.showinfo("Info", "Processing cancellation not yet implemented.")

    def clear_downloads(self):
        """Clear downloaded files"""
        try:
            downloads_dir = Path("downloads")
            if downloads_dir.exists():
                for file in downloads_dir.glob("*"):
                    if file.is_file():
                        file.unlink()
                messagebox.showinfo("Success", "Downloads cleared.")
            else:
                messagebox.showinfo("Info", "No downloads directory found.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to clear downloads: {e}")

    def show_about(self):
        """Show about dialog"""
        messagebox.showinfo(
            "About", 
            "Auto Student GUI\n\n"
            "An enhanced academic assignment processor.\n\n"
            "⚠️ Remember: This tool is for learning assistance only.\n"
            "Always follow your institution's academic integrity policies."
        )

    def on_closing(self):
        """Properly cleanup resources on exit"""
        try:
            # Stop async loop
            if hasattr(self, 'loop') and self.loop and not self.loop.is_closed():
                # Cancel all tasks
                self.loop.call_soon_threadsafe(self.loop.stop)
                
            # Wait for thread to finish
            if hasattr(self, 'thread') and self.thread and self.thread.is_alive():
                self.thread.join(timeout=3)
                
        except Exception as e:
            print(f"Error during cleanup: {e}")
        finally:
            self.destroy()


if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_closing)
    app.mainloop()