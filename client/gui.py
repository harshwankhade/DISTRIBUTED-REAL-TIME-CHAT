"""Lightweight Tkinter desktop client for the Milestone 1 demonstration."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import grpc

from client.api import ChatApi
from proto.chat.v1 import chat_pb2


def _error_text(exc: Exception) -> str:
    if isinstance(exc, grpc.RpcError):
        return f"{exc.code().name}: {exc.details()}"
    return str(exc)


class ChatWindow:
    def __init__(self, api: ChatApi, *, title: str) -> None:
        self.api = api
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry("1000x680")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.channels: list[object] = []
        self.selected_channel_id: str | None = None
        self.stream_call = None
        self.running = True
        self._build_login()

    def _build_login(self) -> None:
        frame = ttk.Frame(self.root, padding=30)
        frame.pack(expand=True)
        ttk.Label(frame, text="Distributed Chat", font=("Segoe UI", 20, "bold")).grid(
            row=0, column=0, columnspan=2, pady=(0, 20)
        )
        ttk.Label(frame, text="Username").grid(row=1, column=0, sticky="e", padx=8, pady=5)
        ttk.Label(frame, text="Password").grid(row=2, column=0, sticky="e", padx=8, pady=5)
        self.username = ttk.Entry(frame, width=30)
        self.password = ttk.Entry(frame, width=30, show="*")
        self.username.grid(row=1, column=1, pady=5)
        self.password.grid(row=2, column=1, pady=5)
        self.password.bind("<Return>", lambda _event: self._login())
        ttk.Button(frame, text="Log in", command=self._login).grid(
            row=3, column=0, columnspan=2, pady=15
        )
        self.login_frame = frame

    def _login(self) -> None:
        username, password = self.username.get().strip(), self.password.get()
        if not username or not password:
            messagebox.showerror("Login", "Enter username and password.")
            return
        try:
            self.api.login(username, password)
        except Exception as exc:
            messagebox.showerror("Login failed", _error_text(exc))
            return
        self.current_username = username
        self.login_frame.destroy()
        self._build_main()
        self._refresh_channels()
        self._schedule_heartbeat()

    def _build_main(self) -> None:
        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill="both", expand=True)
        left = ttk.Frame(outer)
        left.pack(side="left", fill="y", padx=(0, 8))
        ttk.Label(left, text=f"Signed in: {self.current_username}").pack(anchor="w")
        self.channel_list = tk.Listbox(left, width=28, height=24)
        self.channel_list.pack(fill="y", expand=True, pady=8)
        self.channel_list.bind("<<ListboxSelect>>", self._select_channel)
        for label, command in (
            ("Refresh", self._refresh_channels),
            ("Join selected", self._join),
            ("Leave selected", self._leave),
            ("Create channel", self._create_channel),
            ("Admin: create user", self._create_user),
        ):
            ttk.Button(left, text=label, command=command).pack(fill="x", pady=2)

        right = ttk.Frame(outer)
        right.pack(side="right", fill="both", expand=True)
        self.heading = ttk.Label(right, text="Select a channel", font=("Segoe UI", 14, "bold"))
        self.heading.pack(anchor="w")
        self.messages = tk.Text(right, state="disabled", wrap="word")
        self.messages.pack(fill="both", expand=True, pady=8)
        compose = ttk.Frame(right)
        compose.pack(fill="x")
        self.message_entry = ttk.Entry(compose)
        self.message_entry.pack(side="left", fill="x", expand=True)
        self.message_entry.bind("<Return>", lambda _event: self._send())
        ttk.Button(compose, text="Send", command=self._send).pack(side="left", padx=(6, 0))
        actions = ttk.Frame(right)
        actions.pack(fill="x", pady=(8, 0))
        for label, command in (
            ("Smart reply", lambda: self._ask_ai("reply")),
            ("24h summary", lambda: self._ask_ai("summary")),
            ("Next steps", lambda: self._ask_ai("suggestion")),
            ("Upload file", self._upload),
            ("Download by ID", self._download),
        ):
            ttk.Button(actions, text=label, command=command).pack(side="left", padx=2)
        self.status = ttk.Label(right, text="Ready")
        self.status.pack(anchor="w", pady=(8, 0))

    def _set_status(self, value: str) -> None:
        self.status.configure(text=value)

    def _selected_list_channel(self):
        selection = self.channel_list.curselection()
        return self.channels[selection[0]] if selection else None

    def _refresh_channels(self) -> None:
        try:
            self.channels = list(self.api.list_channels())
            self.channel_list.delete(0, "end")
            for channel in self.channels:
                suffix = " [archived]" if channel.archived else ""
                self.channel_list.insert("end", f"{channel.name}{suffix}")
            self._set_status(f"Loaded {len(self.channels)} channel(s)")
        except Exception as exc:
            messagebox.showerror("Channels", _error_text(exc))

    def _select_channel(self, _event=None) -> None:
        channel = self._selected_list_channel()
        if channel is None:
            return
        self.selected_channel_id = channel.channel_id
        self.heading.configure(text=channel.name)
        try:
            history = list(self.api.history(channel.channel_id))
        except Exception as exc:
            self._replace_messages("Join this channel to view its history.\n")
            self._set_status(_error_text(exc))
            return
        self._replace_messages("")
        for message in reversed(history):
            self._append_message(message.sender_username or message.sender_id, message.body)
        self._start_stream(channel.channel_id)

    def _replace_messages(self, value: str) -> None:
        self.messages.configure(state="normal")
        self.messages.delete("1.0", "end")
        self.messages.insert("end", value)
        self.messages.configure(state="disabled")

    def _append_message(self, sender: str, body: str) -> None:
        self.messages.configure(state="normal")
        self.messages.insert("end", f"{sender}: {body}\n")
        self.messages.see("end")
        self.messages.configure(state="disabled")

    def _start_stream(self, channel_id: str) -> None:
        if self.stream_call is not None:
            self.stream_call.cancel()

        def listen() -> None:
            try:
                call = self.api.subscribe_messages(channel_id)
                self.stream_call = call
                for event in call:
                    if not self.running or channel_id != self.selected_channel_id:
                        call.cancel()
                        break
                    if event.type == chat_pb2.CHAT_EVENT_TYPE_MESSAGE:
                        self.root.after(
                            0,
                            self._append_message,
                            event.message.sender_username or event.message.sender_id,
                            event.message.body,
                        )
            except grpc.RpcError as exc:
                if self.running and exc.code() != grpc.StatusCode.CANCELLED:
                    self.root.after(0, self._set_status, _error_text(exc))

        threading.Thread(target=listen, daemon=True).start()

    def _send(self) -> None:
        body = self.message_entry.get().strip()
        if not self.selected_channel_id or not body:
            return
        try:
            self.api.send_message(self.selected_channel_id, body)
            self.message_entry.delete(0, "end")
        except Exception as exc:
            messagebox.showerror("Send failed", _error_text(exc))

    def _join(self) -> None:
        channel = self._selected_list_channel()
        if channel is None:
            return
        try:
            self.api.join_channel(channel.channel_id)
            self._set_status(f"Joined {channel.name}")
            self._select_channel()
        except Exception as exc:
            messagebox.showerror("Join failed", _error_text(exc))

    def _leave(self) -> None:
        channel = self._selected_list_channel()
        if channel is None:
            return
        try:
            self.api.leave_channel(channel.channel_id)
            self._set_status(f"Left {channel.name}")
        except Exception as exc:
            messagebox.showerror("Leave failed", _error_text(exc))

    def _create_channel(self) -> None:
        name = simpledialog.askstring("Create channel", "Channel name:", parent=self.root)
        if not name:
            return
        try:
            self.api.create_channel(name)
            self._refresh_channels()
        except Exception as exc:
            messagebox.showerror("Create channel", _error_text(exc))

    def _create_user(self) -> None:
        username = simpledialog.askstring("Admin", "New username:", parent=self.root)
        if not username:
            return
        password = simpledialog.askstring("Admin", "Temporary password:", show="*", parent=self.root)
        if not password:
            return
        role = simpledialog.askstring("Admin", "Role (user/admin):", initialvalue="user", parent=self.root)
        if not role:
            return
        try:
            user = self.api.create_user(username, password, role)
            self._set_status(f"Created {user.username} ({user.role})")
        except Exception as exc:
            messagebox.showerror("Create user", _error_text(exc))

    def _ask_ai(self, operation: str) -> None:
        if not self.selected_channel_id:
            return
        self._set_status("Waiting for local AI...")

        def work() -> None:
            try:
                method = getattr(self.api, {"reply": "smart_reply", "summary": "summary", "suggestion": "suggestion"}[operation])
                answer, status = method(self.selected_channel_id)
                self.root.after(0, self._show_ai, operation, answer, status)
            except Exception as exc:
                self.root.after(0, messagebox.showerror, "AI", _error_text(exc))

        threading.Thread(target=work, daemon=True).start()

    def _show_ai(self, operation: str, answer: str, status: str) -> None:
        self._set_status(status)
        if operation == "reply":
            self.message_entry.delete(0, "end")
            self.message_entry.insert(0, answer)
        else:
            messagebox.showinfo("AI result", answer)

    def _upload(self) -> None:
        if not self.selected_channel_id:
            return
        filename = filedialog.askopenfilename(parent=self.root)
        if not filename:
            return
        try:
            metadata = self.api.upload(self.selected_channel_id, Path(filename))
            messagebox.showinfo("Uploaded", f"File ID: {metadata.file_id}\nSHA-256: {metadata.checksum_sha256}")
        except Exception as exc:
            messagebox.showerror("Upload", _error_text(exc))

    def _download(self) -> None:
        file_id = simpledialog.askstring("Download", "File ID:", parent=self.root)
        if not file_id:
            return
        filename = filedialog.asksaveasfilename(parent=self.root)
        if not filename:
            return
        try:
            self.api.download(file_id, Path(filename))
            self._set_status("Download complete and checksum verified")
        except Exception as exc:
            messagebox.showerror("Download", _error_text(exc))

    def _schedule_heartbeat(self) -> None:
        if not self.running or self.api.token is None:
            return
        try:
            self.api.heartbeat()
        except grpc.RpcError as exc:
            self._set_status(_error_text(exc))
        self.root.after(5000, self._schedule_heartbeat)

    def close(self) -> None:
        self.running = False
        if self.stream_call is not None:
            self.stream_call.cancel()
        try:
            self.api.logout()
        except grpc.RpcError:
            pass
        self.api.close()
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()
