"""Lightweight Tkinter desktop client for the Milestone 1 demonstration."""

from __future__ import annotations

import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, simpledialog, ttk

import grpc

from client.api import ChatApi
from proto.chat.v1 import chat_pb2


def _error_text(exc: Exception) -> str:
    if isinstance(exc, grpc.RpcError):
        return f"{exc.code().name}: {exc.details()}"
    return str(exc)


def _owned_channels(channels, owner_id: str):
    return sorted(
        (channel for channel in channels if channel.owner_id == owner_id),
        key=lambda channel: channel.name.casefold(),
    )


def _presence_text(status: str | None) -> str:
    return status if status in {"online", "offline"} else "unknown"


def _online_member_count(members, statuses: dict[str, str]) -> int:
    return sum(statuses.get(member.user_id) == "online" for member in members)


class _ChannelPicker(simpledialog.Dialog):
    """Modal dropdown for choosing one of the signed-in user's channels."""

    def __init__(self, parent: tk.Tk, username: str, channels) -> None:
        self.username = username
        self.channels = channels
        self.result = None
        super().__init__(parent, title="Add user to channel")

    def body(self, master):
        ttk.Label(master, text=f"Choose a channel to add {self.username}:").pack(
            anchor="w", pady=(0, 8)
        )
        self.choice = ttk.Combobox(
            master, values=[channel.name for channel in self.channels],
            state="readonly", width=38,
        )
        self.choice.pack(fill="x")
        return self.choice

    def validate(self) -> bool:
        if self.choice.current() < 0:
            messagebox.showwarning(
                "Select channel", "Choose a channel from the dropdown.", parent=self
            )
            return False
        return True

    def apply(self) -> None:
        self.result = self.channels[self.choice.current()]


class ChatWindow:
    def __init__(self, api: ChatApi, *, title: str) -> None:
        self.api = api
        self.root = tk.Tk()
        self.root.title(title)
        self.root.geometry("1000x680")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.channels: list[object] = []
        self.users: list[object] = []
        self.visible_members: list[object] = []
        self.presence_by_user: dict[str, str] = {}
        self._presence_results: Queue[dict[str, str]] = Queue()
        self._presence_fetch_in_progress = False
        self.current_user_id = ""
        self.seen_join_requests: set[str] = set()
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
        ttk.Button(frame, text="Log in", command=self._login).grid(row=3, column=0, pady=15)
        ttk.Button(frame, text="Register", command=self._register).grid(row=3, column=1, pady=15)
        self.login_frame = frame

    def _login(self) -> None:
        username, password = self.username.get().strip(), self.password.get()
        if not username or not password:
            messagebox.showerror("Login", "Enter username and password.")
            return
        try:
            user = self.api.login(username, password)
        except Exception as exc:
            messagebox.showerror("Login failed", _error_text(exc))
            return
        self._signed_in(user)

    def _register(self) -> None:
        username, password = self.username.get().strip(), self.password.get()
        if not username or not password:
            messagebox.showerror("Register", "Enter a username and password.")
            return
        try:
            user = self.api.register(username, password)
        except Exception as exc:
            messagebox.showerror("Registration failed", _error_text(exc))
            return
        self._signed_in(user)

    def _signed_in(self, user) -> None:
        self.current_user_id = user.user_id
        self.current_username = user.username
        self.login_frame.destroy()
        self._build_main()
        self._refresh_channels()
        self._schedule_heartbeat()
        self._schedule_presence_refresh()
        self._drain_presence_results()
        self._poll_join_requests()

    def _build_main(self) -> None:
        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill="both", expand=True)
        left = ttk.Frame(outer)
        left.pack(side="left", fill="y", padx=(0, 8))
        ttk.Label(left, text=f"Signed in: {self.current_username}").pack(anchor="w")
        ttk.Label(left, text="Registered users").pack(anchor="w", pady=(8, 0))
        self.user_list = tk.Listbox(left, width=28, height=7)
        self.user_list.pack(fill="x", pady=(2, 6))
        ttk.Separator(left, orient="horizontal").pack(fill="x", pady=5)
        ttk.Label(left, text="Channels").pack(anchor="w")
        self.channel_list = tk.Listbox(left, width=28, height=15)
        self.channel_list.pack(fill="y", expand=True, pady=8)
        self.channel_list.bind("<<ListboxSelect>>", self._select_channel)
        for label, command in (
            ("Refresh", self._refresh_channels),
            ("Request to join", self._join),
            ("Leave selected", self._leave),
            ("Create channel", self._create_channel),
            ("Owner: add selected user", self._add_selected_user),
        ):
            ttk.Button(left, text=label, command=command).pack(fill="x", pady=2)
        self.delete_channel_button = ttk.Button(
            left, text="Owner: delete channel", command=self._delete_channel
        )

        right = ttk.Frame(outer)
        right.pack(side="right", fill="both", expand=True)
        self.heading = ttk.Label(right, text="Select a channel", font=("Segoe UI", 14, "bold"))
        self.heading.pack(anchor="w")
        content = ttk.Frame(right)
        content.pack(fill="both", expand=True, pady=8)
        members_panel = ttk.Frame(content)
        members_panel.pack(side="right", fill="y", padx=(8, 0))
        self.members_header = ttk.Label(members_panel, text="Channel members")
        self.members_header.pack(anchor="w")
        self.members_text = tk.Text(members_panel, width=25, state="disabled", wrap="none")
        self.members_text.pack(fill="y", expand=True)
        self.messages = tk.Text(content, state="disabled", wrap="word")
        self.messages.pack(side="left", fill="both", expand=True)
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

    def _render_users(self, selected_user_id: str | None = None) -> None:
        if selected_user_id is None:
            selection = self.user_list.curselection()
            if selection and selection[0] < len(self.users):
                selected_user_id = self.users[selection[0]].user_id
        scroll_position = self.user_list.yview()[0]
        self.user_list.delete(0, "end")
        for index, user in enumerate(self.users):
            status = _presence_text(self.presence_by_user.get(user.user_id))
            self.user_list.insert("end", f"{user.username} ({status})")
            if user.user_id == selected_user_id:
                self.user_list.selection_set(index)
        self.user_list.yview_moveto(scroll_position)

    def _refresh_channels(self) -> None:
        try:
            selected_user = (
                self.users[self.user_list.curselection()[0]].user_id
                if self.user_list.curselection() else None
            )
            selected_channel_id = self.selected_channel_id
            self.users = list(self.api.list_users())
            self._render_users(selected_user)
            self.channels = list(self.api.list_channels())
            self.channel_list.delete(0, "end")
            selected_found = False
            for index, channel in enumerate(self.channels):
                suffix = " [owner]" if channel.owner_id == self.current_user_id else (
                    " [member]" if channel.is_member else " [join required]"
                )
                self.channel_list.insert("end", f"{channel.name}{suffix}")
                if channel.channel_id == selected_channel_id:
                    self.channel_list.selection_set(index)
                    selected_found = True
            if selected_channel_id and not selected_found:
                self._clear_selected_channel()
            self._set_status(f"Loaded {len(self.channels)} channel(s)")
        except Exception as exc:
            messagebox.showerror("Channels", _error_text(exc))

    def _select_channel(self, _event=None) -> None:
        channel = self._selected_list_channel()
        if channel is None:
            return
        self.selected_channel_id = channel.channel_id
        self.heading.configure(text=channel.name)
        if channel.owner_id == self.current_user_id:
            self.delete_channel_button.pack(fill="x", pady=2)
        else:
            self.delete_channel_button.pack_forget()
        if not channel.is_member:
            if self.stream_call is not None:
                self.stream_call.cancel()
            self._replace_messages("Request to join. The channel owner must approve you before you can chat.\n")
            self._replace_members("Join to view members.\n")
            return
        self._refresh_members(channel)
        try:
            history = list(self.api.history(channel.channel_id))
            files = list(self.api.list_files(channel.channel_id))
        except Exception as exc:
            self._replace_messages("Join this channel to view its history.\n")
            self._set_status(_error_text(exc))
            return
        self._replace_messages("")
        timeline = [
            (message.created_at.ToDatetime(), "message", message)
            for message in history
        ]
        timeline.extend(
            (metadata.created_at.ToDatetime(), "file", metadata)
            for metadata in files
        )
        for _created_at, kind, item in sorted(timeline, key=lambda entry: entry[0]):
            if kind == "message":
                self._append_message(
                    item.sender_username or item.sender_id, item.body
                )
            else:
                self._append_file(item)
        self._start_stream(channel.channel_id)

    def _clear_selected_channel(self) -> None:
        self.selected_channel_id = None
        if self.stream_call is not None:
            self.stream_call.cancel()
            self.stream_call = None
        self.delete_channel_button.pack_forget()
        self.heading.configure(text="Select a channel")
        self._replace_messages("")
        self._replace_members("")

    def _replace_members(self, value: str) -> None:
        self.visible_members = []
        self.members_header.configure(text="Channel members")
        self.members_text.configure(state="normal")
        self.members_text.delete("1.0", "end")
        self.members_text.insert("end", value)
        self.members_text.configure(state="disabled")

    def _refresh_members(self, channel) -> None:
        try:
            members = self.api.list_members(channel.channel_id)
        except Exception as exc:
            self._replace_members("Members unavailable.\n")
            self._set_status(_error_text(exc))
            return
        self.visible_members = list(members)
        self._render_members(channel)

    def _render_members(self, channel) -> None:
        count = _online_member_count(self.visible_members, self.presence_by_user)
        unknown = sum(
            _presence_text(self.presence_by_user.get(member.user_id)) == "unknown"
            for member in self.visible_members
        )
        suffix = f", {unknown} unknown" if unknown else ""
        self.members_header.configure(text=f"Channel members ({count} online{suffix})")
        self.members_text.configure(state="normal")
        self.members_text.delete("1.0", "end")
        for member in self.visible_members:
            status = _presence_text(self.presence_by_user.get(member.user_id))
            self.members_text.insert("end", f"{member.username} ({status})")
            if channel.owner_id == self.current_user_id and member.user_id != self.current_user_id:
                button = ttk.Button(
                    self.members_text, text="Remove",
                    command=lambda item=member: self._remove_member(channel, item),
                )
                self.members_text.insert("end", "  ")
                self.members_text.window_create("end", window=button)
            self.members_text.insert("end", "\n")
        self.members_text.configure(state="disabled")

    def _apply_presence(self, statuses: dict[str, str]) -> None:
        self.presence_by_user.update(statuses)
        self._render_users()
        selected = self._selected_list_channel()
        if selected is not None and selected.is_member:
            self._render_members(selected)

    def _fetch_presence(self, user_ids: tuple[str, ...]) -> None:
        def fetch(user_id: str) -> tuple[str, str]:
            try:
                status = self.api.get_presence(user_id)
            except Exception:
                status = "unknown"  # A failed RPC is not proof the user is offline.
            return user_id, _presence_text(status)

        try:
            with ThreadPoolExecutor(max_workers=min(8, len(user_ids))) as pool:
                result = dict(pool.map(fetch, user_ids))
        except Exception:
            result = {user_id: "unknown" for user_id in user_ids}
        self._presence_results.put(result)

    def _schedule_presence_refresh(self) -> None:
        if not self.running or self.api.token is None:
            return
        if not self._presence_fetch_in_progress:
            user_ids = {user.user_id for user in self.users}
            user_ids.update(member.user_id for member in self.visible_members)
            if user_ids:
                self._presence_fetch_in_progress = True
                threading.Thread(
                    target=self._fetch_presence, args=(tuple(user_ids),), daemon=True
                ).start()
        self.root.after(5000, self._schedule_presence_refresh)

    def _drain_presence_results(self) -> None:
        if not self.running:
            return
        try:
            while True:
                result = self._presence_results.get_nowait()
                self._presence_fetch_in_progress = False
                self._apply_presence(result)
        except Empty:
            pass
        self.root.after(200, self._drain_presence_results)

    def _remove_member(self, channel, member) -> None:
        if not messagebox.askyesno(
            "Remove member", f"Remove {member.username} from {channel.name}?", parent=self.root
        ):
            return
        try:
            self.api.manage_member(channel.channel_id, member.user_id, False)
            self._refresh_members(channel)
            self._set_status(f"Removed {member.username} from {channel.name}")
        except Exception as exc:
            messagebox.showerror("Remove member", _error_text(exc))

    def _delete_channel(self) -> None:
        channel = self._selected_list_channel()
        if channel is None or channel.owner_id != self.current_user_id:
            return
        if not messagebox.askyesno(
            "Delete channel",
            f"Permanently delete {channel.name}, all its members, messages, and file records?\n"
            "Uploaded file bytes will remain on disk but cannot be accessed in the app.",
            parent=self.root,
        ):
            return
        try:
            self.api.delete_channel(channel.channel_id)
            self._clear_selected_channel()
            self._refresh_channels()
            self._set_status(f"Deleted {channel.name}")
        except Exception as exc:
            messagebox.showerror("Delete channel", _error_text(exc))

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

    def _append_file(self, metadata) -> None:
        self.messages.configure(state="normal")
        uploader = metadata.uploader_username or metadata.uploader_id
        self.messages.insert("end", f"{uploader} uploaded {metadata.original_name}  ")
        button = ttk.Button(
            self.messages,
            text="Download",
            command=lambda item=metadata: self._download_file(item),
        )
        self.messages.window_create("end", window=button)
        self.messages.insert("end", "\n")
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
                    elif event.type == chat_pb2.CHAT_EVENT_TYPE_FILE:
                        self.root.after(0, self._append_file, event.file)
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
            if channel.is_member:
                self._set_status(f"Already a member of {channel.name}")
                return
            self.api.join_channel(channel.channel_id)
            self._set_status(f"Request sent to the owner of {channel.name}")
        except Exception as exc:
            messagebox.showerror("Join failed", _error_text(exc))

    def _leave(self) -> None:
        channel = self._selected_list_channel()
        if channel is None:
            return
        try:
            self.api.leave_channel(channel.channel_id)
            self._set_status(f"Left {channel.name}")
            self._refresh_channels()
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

    def _add_selected_user(self) -> None:
        selection = self.user_list.curselection()
        if not selection:
            messagebox.showinfo("Membership", "Select a registered user first.")
            return
        user = self.users[selection[0]]
        try:
            owned = _owned_channels(self.api.list_channels(), self.current_user_id)
        except Exception as exc:
            messagebox.showerror("Membership", _error_text(exc))
            return
        if not owned:
            messagebox.showinfo("Membership", "Create a channel first; you do not own any channels.")
            return
        channel = _ChannelPicker(self.root, user.username, owned).result
        if channel is None:
            return
        try:
            if any(member.user_id == user.user_id for member in self.api.list_members(channel.channel_id)):
                messagebox.showinfo("Membership", f"{user.username} is already in {channel.name}.")
                return
            self.api.manage_member(channel.channel_id, user.user_id, True)
            if self.selected_channel_id == channel.channel_id:
                self._refresh_members(channel)
            self._set_status(f"Added {user.username} to {channel.name}")
        except Exception as exc:
            messagebox.showerror("Membership", _error_text(exc))

    def _poll_join_requests(self) -> None:
        if not self.running or self.api.token is None:
            return
        try:
            previous = {channel.channel_id: channel.is_member for channel in self.channels}
            self._refresh_channels()
            for channel in self.channels:
                if channel.owner_id != self.current_user_id:
                    continue
                for pending in self.api.list_join_requests(channel.channel_id):
                    if pending.request_id in self.seen_join_requests:
                        continue
                    approved = messagebox.askyesno(
                        "Join request",
                        f"Allow {pending.user.username} to join {channel.name}?",
                        parent=self.root,
                    )
                    self.api.decide_join_request(pending.request_id, approved)
                    self.seen_join_requests.add(pending.request_id)
            selected = self._selected_list_channel()
            if selected and previous.get(selected.channel_id) != selected.is_member:
                self._select_channel()
            elif selected and selected.is_member:
                self._refresh_members(selected)
        except Exception as exc:
            self._set_status(_error_text(exc))
        self.root.after(5000, self._poll_join_requests)

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

    def _download_file(self, metadata) -> None:
        filename = filedialog.asksaveasfilename(
            parent=self.root,
            initialfile=metadata.original_name,
        )
        if not filename:
            return
        try:
            self.api.download(metadata.file_id, Path(filename))
            self._set_status(
                f"Downloaded {metadata.original_name}; checksum verified"
            )
        except Exception as exc:
            messagebox.showerror("Download", _error_text(exc))

    def _schedule_heartbeat(self) -> None:
        if not self.running or self.api.token is None:
            return
        try:
            status = self.api.heartbeat()
            self._apply_presence({self.current_user_id: _presence_text(status)})
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
