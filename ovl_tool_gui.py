import contextlib
import os
import shutil
import logging
import tempfile
from pathlib import PurePath

from gui import widgets, startup, GuiOptions  # Import widgets before everything except built-ins!
from gui.widgets import get_icon
from ovl_util.logs import get_stdout_handler
from modules import walker
from generated.formats.ovl import games, OvlFile
from generated.formats.ovl_base.enums.Compression import Compression
from PyQt5 import QtWidgets, QtGui, QtCore
from typing import Any, Optional


class MainWindow(widgets.MainWindow):

	search_files = QtCore.pyqtSignal(tuple)

	def __init__(self, opts: GuiOptions):
		widgets.MainWindow.__init__(self, "OVL Tool", opts=opts)
		self.resize(800, 600)
		self.setAcceptDrops(True)
		self.suppress_popups = False

		self.reporter = widgets.Reporter()
		self.ovl_data = OvlFile()
		self.ovl_data.reporter = self.reporter
		self.ovl_data.cfg = self.cfg

		exts = " ".join([f"*{ext}" for ext in self.ovl_data.formats_dict.extractables])
		self.filter = f"Supported files ({exts})"

		self.file_widget = self.make_file_widget()

		self.ovl_game_choice = widgets.LabelCombo("Game", [g.value for g in games], editable=False, changed_fn=self.game_changed)
		self.ovl_game_choice.setToolTip("Game version of current OVL")
		self.ovl_game_choice.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)

		self.compression_choice = widgets.LabelCombo(
			"Compression", [c.name for c in Compression], editable=False, changed_fn=self.compression_changed,
			activated_fn=self.compression_touched_by_user)
		self.compression_choice.setToolTip("Compression of current OVL")
		self.compression_choice.setSizePolicy(QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed)

		self.extract_types_choice = widgets.CheckableComboBox()
		self.extract_types_choice.addItems(self.ovl_data.formats_dict.extractables)
		self.extract_types_choice.setToolTip("Select file formats processed by batch tasks")

		if "games" not in self.cfg:
			self.cfg["games"] = {}
		self.installed_games = widgets.GamesWidget(
			self,
			[g.value for g in games],
			game_chosen_fn=self.set_ovl_game_choice_game,
			file_dbl_click_fn=self.open_clicked_file,
			search_content_fn=self.search_ovl_contents,
			actions={
				QtWidgets.QAction(get_icon("extract"), "Unpack All"): self.extract_all_batch,
				QtWidgets.QAction(get_icon("rename"), "Rename Files"): self.rename_batch,
				QtWidgets.QAction(get_icon("rename_contents"), "Rename Contents"): self.rename_contents_batch,
				})
		self.installed_games.set_selected_game()

		# create the table
		self.files_container = widgets.SortableTable(
			["Name", "File Type"], self.ovl_data.formats_dict.ignore_types, ignore_drop_type="OVL", opt_hide=True,
			actions={
				# QtWidgets.QAction("Test action"): self.run_action,
			})
		# connect the interaction functions
		self.files_container.table.table_model.member_renamed.connect(self.rename_handle)
		self.files_container.table.files_dragged.connect(self.drag_files)
		self.files_container.table.files_dropped.connect(self.inject_files)
		self.files_container.table.file_selected_count.connect(self.update_file_counts)
		# self.files_container.table.file_selected.connect(self.show_dependencies)

		self.included_ovls_view = widgets.RelativePathCombo(self, self.file_widget)
		self.included_ovls_view.setToolTip(
			"These OVL files are loaded by the current OVL file, so their files are included")
		self.included_ovls_view.entries_changed.connect(self.update_includes)

		# toggles
		self.e_name_old = QtWidgets.QTextEdit("")
		self.e_name_old.setPlaceholderText("Find")
		self.e_name_old.setToolTip("Old strings - one item per line")
		self.e_name_new = QtWidgets.QTextEdit("")
		self.e_name_new.setPlaceholderText("Replace")
		self.e_name_new.setToolTip("New strings - one item per line")
		self.e_name_new.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
		self.e_name_old.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
		self.e_name_old.setTabChangesFocus(True)
		self.e_name_new.setTabChangesFocus(True)

		grid = QtWidgets.QGridLayout()
		grid.addWidget(self.e_name_old, 0, 0, 3, 1)
		grid.addWidget(self.e_name_new, 0, 1, 3, 1)
		grid.addWidget(self.ovl_game_choice, 0, 2)
		grid.addWidget(self.compression_choice, 1, 2)
		grid.addWidget(self.extract_types_choice, 2, 2)

		self.stdout_handler = get_stdout_handler("ovl_tool_gui")  # self.log_name not set until after init

		left_frame = widgets.pack_in_vbox(
			self.installed_games,
			self.installed_games.search,
			self.installed_games.dirs,
			margins=(0, 0, 1, 0))
		right_frame = widgets.pack_in_vbox(
			self.file_widget,
			self.files_container,
			self.included_ovls_view,
			margins=(3, 0, 0, 0))
		self.layout_splitter(grid, left_frame, right_frame)

		# Setup Menus
		main_menu = self.menu_bar
		file_menu = main_menu.addMenu('File')
		edit_menu = main_menu.addMenu('Edit')
		util_menu = main_menu.addMenu('Util')
		help_menu = main_menu.addMenu('Help')
		button_data = (
			(file_menu, "New", self.file_widget.ask_open_dir, "CTRL+N", "new"),
			(file_menu, "Open", self.file_widget.ask_open, "CTRL+O", "dir"),
			(file_menu, "Save", self.file_widget.ask_save, "CTRL+S", "save"),
			(file_menu, "Save As", self.file_widget.ask_save_as, "CTRL+SHIFT+S", "save"),
			(file_menu, "Exit", self.close, "", "exit"),
			(edit_menu, "Unpack All", self.extract_all, "CTRL+U", "extract"),
			(edit_menu, "Inject", self.inject_ask, "CTRL+I", "inject"),
			(edit_menu, "Rename Files", self.rename, "CTRL+R", "rename"),
			(edit_menu, "Rename Contents", self.rename_contents, "CTRL+SHIFT+R", "rename_contents"),
			(edit_menu, "Rename Both", self.rename_both, "CTRL+ALT+R", ""),
			(edit_menu, "Remove Selected", self.remove, "DEL", "remove"),
			(edit_menu, "Load Included OVL List", self.load_included_ovls, "", ""),
			(edit_menu, "Export Included OVL List", self.save_included_ovls, "", ""),
			(edit_menu, "Preferences", self.open_cfg_editor, "CTRL+,", "preferences"),
			(util_menu, "Inspect ms2", self.inspect_models, "", "ms2", True),
			(util_menu, "Inspect fgm", self.walker_fgm, "", "fgm", True),
			(util_menu, "Inspect manis", self.walker_manis, "", "manis", True),
			(util_menu, "Generate Hash Table", self.walker_hash, "", ""),
			(util_menu, "Dump Debug Data", self.dump_debug_data, "", "dump_debug", True),
			(util_menu, "Open Tools Dir", self.open_tools_dir, "", "home"),
			(util_menu, "Export File List", self.save_file_list, "", ""),
			(util_menu, "Compare with other OVL", self.compare_ovls, "", ""),
			(help_menu, "Report Bug", self.report_bug, "", "report"),
			(help_menu, "Documentation", self.online_support, "", "manual"))
		self.add_to_menu(button_data)

		separator_action = self.actions['generate hash table']
		util_menu.insertSeparator(separator_action)

		self.file_info = QtWidgets.QLabel(self)
		
		self.finfo_sep = QtWidgets.QFrame(self)
		self.finfo_sep.setFrameStyle(QtWidgets.QFrame.Shape.VLine)
		self.finfo_sep.setStyleSheet("color: #777;")
		self.finfo_sep.setMaximumHeight(15)
		self.finfo_sep.hide()

		self.status_bar.insertPermanentWidget(2, self.finfo_sep)
		self.status_bar.insertPermanentWidget(3, self.file_info)

		log_level = self.cfg.get("logger_level", "INFO")
		self.set_log_level.emit(log_level)

		self.search_files.connect(self.show_search_results)
		self.search_views = {}
		# do these at the end to make sure their requirements have been initialized
		reporter = self.ovl_data.reporter
		reporter.files_list.connect(self.update_files_ui)
		reporter.included_ovls_list.connect(self.included_ovls_view.set_data)
		reporter.warning_msg.connect(self.notify_user)
		reporter.progress_percentage.connect(self.set_progress)
		reporter.success_msg.connect(self.set_msg_temporarily)
		reporter.current_action.connect(self.set_msg_temporarily)
		self.run_in_threadpool(self.ovl_data.load_hash_table)
		self.preferences_widget = None

	def open_cfg_editor(self):
		self.preferences_widget = widgets.ConfigWindow(self.cfg)
		self.preferences_widget.setWindowTitle(f"Preferences")
		# self.preferences_widget.setGeometry(QtCore.QRect(100, 100, 1000, 600))
		self.preferences_widget.show()

	def abs_path_from_row(self, row_data):
		start_dir = self.installed_games.get_root()
		full_path = os.path.join(start_dir, row_data[2])
		return os.path.normpath(full_path)

	def search_result_open(self, row_data):
		ovl_path = self.abs_path_from_row(row_data)
		self.file_widget.open_file(ovl_path)

	def search_result_show(self, row_data):
		ovl_path = self.abs_path_from_row(row_data)
		logging.info(f"Showing {ovl_path} in Explorer")
		os.startfile(os.path.dirname(ovl_path))

	def run_action(self, *args):
		print("action", args)

	def close(self) -> bool:
		for results_container in list(self.search_views.values()):
			results_container.close()
		return super().close()

	def get_file_count_text(self):
		return f"{self.files_container.table.table_model.rowCount()} items"
	
	def update_file_counts(self, selected_count=0):
		text = self.get_file_count_text()
		if selected_count > 0:
			text = f"{selected_count} / {text} selected"
		self.file_info.setText(text)
		self.finfo_sep.show()

	def show_search_results(self, tup):
		search_str, results = tup
		results_container = self.search_views.get(search_str)
		if results_container:
			results_container.set_data(results)

	def search_ovl_contents(self, search_str):
		search_str = search_str.lower()
		if search_str not in self.search_views:
			results_container = widgets.SortableTable(
				["Name", "File Type", "OVL"], self.ovl_data.formats_dict.ignore_types, ignore_drop_type="OVL", opt_hide=True,
				actions={
					QtWidgets.QAction("Open in OVL Tool"): self.search_result_open,
					QtWidgets.QAction("Show in Explorer"): self.search_result_show,
				})
			results_container.setWindowTitle(f"Results for: {search_str}")
			results_container.setGeometry(QtCore.QRect(100, 100, 1000, 600))
			results_container.show()

			def remove_view():
				self.search_views.pop(search_str)

			results_container.closed.connect(remove_view)
			self.search_views[search_str] = results_container

			start_dir = self.installed_games.get_root()
			# thread this to immediately show the window
			self.run_in_threadpool(walker.search_for_files_in_ovls, (), self, start_dir, search_str)
		else:
			logging.warning(f"Search results for '{search_str}' are still open")

	def notify_user(self, msg_list):
		msg = msg_list[0]
		details = msg_list[1] if len(msg_list) > 1 else None
		if self.suppress_popups:
			logging.warning(f"Dragging encountered an error: {details}")
		else:
			self.showwarning(msg, details=details)

	def enable_gui_options(self, enable=True):
		self.compression_choice.setEnabled(enable)
		self.ovl_game_choice.setEnabled(enable)
		# just disable all actions
		for action_name in self.actions.keys():
			self.actions[action_name.lower()].setEnabled(enable)

	def dump_debug_data(self, ):
		self.ovl_data.dump_debug_data()

	def compare_ovls(self):
		selected_file_names = self.files_container.table.get_selected_files()
		if not selected_file_names:
			self.showwarning("Please select files to compare first")
			return
		if self.is_open_ovl():
			filepath = self.file_widget.get_open_file_name(f'Open OVL to compare with')
			if filepath:
				other_ovl_data = OvlFile()
				other_ovl_data.load_hash_table()
				other_ovl_data.load(filepath)
				for file_name in selected_file_names:
					try:
						loader_a = self.ovl_data.loaders[file_name]
						loader_b = other_ovl_data.loaders[file_name]
						if loader_a == loader_b:
							logging.info(f"'{file_name}' is the same")
						else:
							logging.warning(f"'{file_name}' differs")
					except:
						logging.exception(f"Could not compare '{file_name}'")

	def set_ovl_game_choice_game(self, game=None):
		# logging.debug(f"Setting OVL game to {game}")
		self.ovl_game_choice.entry.setText(game)

	@contextlib.contextmanager
	def log_level_override(self, level):
		# temporarily disable spamming the log widget
		log_level = self.cfg.get("logger_level", "INFO")
		self.set_log_level.emit(level)
		yield
		# go back to original log level
		self.set_log_level.emit(log_level)

	def handle_path(self, save_over=True, batch=False):
		if batch:
			# get path
			selected_dir = self.walk_root()
			if selected_dir:
				with self.no_popups():
					with self.log_level_override("WARNING"):
						for ovl_path in walker.walk_type(selected_dir, extension=".ovl"):
							# open ovl file
							self.open(ovl_path, threaded=False)
							# todo transition to open_file api for consistency
							#      but this must not spawn a new thread so that save_over works
							#      clear logger after each file, but self.file_widget.open_file would do that
							# self.file_widget.open_file(ovl_path)
							# process each
							yield self.ovl_data
							if save_over:
								self.save(ovl_path, threaded=False)
			else:
				self.showwarning("Select a root directory!")
		# just the one that's currently open, do not save over
		elif self.is_open_ovl():
			yield self.ovl_data

	def open_clicked_file(self, filepath: str):
		# handle double clicked file paths
		try:
			if filepath.lower().endswith(".ovl"):
				self.file_widget.open_file(filepath)
		except:
			self.handle_error("Clicked dir failed, see log!")

	@staticmethod
	def open_tools_dir():
		os.startfile(os.path.abspath(os.path.dirname(__file__)))

	@contextlib.contextmanager
	def no_popups(self):
		self.suppress_popups = True
		yield
		self.suppress_popups = False

	def drag_files(self, file_names):
		# logging.debug(f"Dragging {file_names}")
		with self.no_popups():
			drag = QtGui.QDrag(self)
			data = QtCore.QMimeData()
			temp_dir = tempfile.mkdtemp("-cobra")
			try:
				out_paths = self.ovl_data.extract(temp_dir, only_names=file_names)
				if out_paths:
					# make relative to output folder
					pure_paths = (PurePath(os.path.relpath(path, temp_dir)) for path in out_paths)
					rel_out_paths = set()
					for p in pure_paths:
						# get the first dir in the path
						if len(p.parents) > 1:
							rel_out_paths.add(str(p.parents[-2]))
						# no dir, just the file itself
						else:
							rel_out_paths.add(str(p))
					# join the children back to the temp_dir
					out_paths = set(os.path.join(temp_dir, p) for p in rel_out_paths)
					# set paths to mime
					data.setUrls([QtCore.QUrl.fromLocalFile(path) for path in out_paths])
					drag.setMimeData(data)
					drag.exec_()
			except:
				self.handle_error("Dragging failed, see log!")
			shutil.rmtree(temp_dir)

	def rename_handle(self, old_name, new_name):
		"""this manages the renaming of a single entry"""
		# force new name to be lowercase
		names = {(old_name, new_name.lower()), }
		try:
			self.ovl_data.rename(names)
			self.set_dirty()
		except:
			self.handle_error("Renaming failed, see log!")

	def game_changed(self, game: Optional[str] = None):
		"""Updates game for self.ovl_data from current GUI selection"""
		if game is None:
			game = self.ovl_game_choice.entry.currentText()
		logging.info(f"Setting OVL version to {game}")
		self.ovl_data.game = game

	def compression_changed(self, compression: str):
		compression_value = Compression[compression]
		self.ovl_data.user_version.compression = compression_value
		# self.set_dirty()
		
	def compression_touched_by_user(self, compression: str):
		# emitted regardless of change - no way to compare to the old value
		self.set_dirty()

	def show_dependencies(self, file_index):
		# just an example of what can be done when something is selected
		file_entry = self.ovl_data.files[file_index]

	def open(self, filepath, threaded=True):
		if filepath:
			commands = {"game": self.ovl_game_choice.entry.currentText()}
			self.set_clean()
			logging.debug(f"Loading threaded {threaded}")
			if threaded:
				self.run_in_threadpool(self.ovl_data.load, (self.set_clean, ), filepath, commands)
			else:
				try:
					self.ovl_data.load(filepath, commands)
				except:
					logging.debug(self.ovl_data)
					self.handle_error("OVL loading failed, see log!")

	def open_dir(self, dirpath: str) -> None:
		self.create_ovl(dirpath)
		self.set_dirty()

	def choices_update(self):
		self.set_ovl_game_choice_game(self.ovl_data.game)
		self.compression_choice.entry.setText(self.ovl_data.user_version.compression.name)

	def create_ovl(self, ovl_dir):
		# clear the ovl
		self.ovl_data.clear()
		self.game_changed()
		try:
			self.ovl_data.create(ovl_dir)
		except:
			self.handle_error("Creating OVL failed, see log!")

	def is_open_ovl(self):
		if self.file_widget.filename or self.file_widget.dirty:
			return True
		else:
			self.showwarning("You must open an OVL file first!")

	def update_files_ui(self, f_list):
		"""Give table widget new files"""
		with self.reporter.log_duration(f"Loading {len(f_list)} files into GUI"):
			self.files_container.set_data(f_list)
			self.update_file_counts()

	def update_includes(self, includes):
		self.ovl_data.included_ovl_names = includes
		self.set_dirty()

	def save(self, filepath, threaded=True):
		"""Saves ovl to file_widget.filepath, clears dirty flag"""
		if threaded:
			self.run_in_threadpool(self.ovl_data.save, (self.set_clean, ), filepath)
		else:
			try:
				self.ovl_data.save(filepath)
				self.set_clean()
			except:
				self.handle_error("Saving OVL failed, see log!")

	def extract_all(self):
		if self.is_open_ovl():
			self.extract_all_ask(batch=False)

	def extract_all_ask(self, batch=False):
		out_dir = QtWidgets.QFileDialog.getExistingDirectory(self, 'Output folder', self.cfg.get("dir_extract", "C://"), )
		if out_dir:
			self.cfg["dir_extract"] = out_dir
			self.run_in_threadpool(self._extract_all, (), out_dir, batch)

	def extract_all_batch(self):
		self.extract_all_ask(batch=True)

	def _extract_all(self, out_dir, batch=False):
		_out_dir = out_dir
		# check using a filter to extract mimes
		only_types = self.extract_types_choice.currentData()
		selected_dir = self.walk_root()
		for ovl in self.handle_path(save_over=False, batch=batch):
			# for bulk extraction, add the ovl basename to the path to avoid overwriting
			if batch:
				rel_p = os.path.relpath(ovl.path_no_ext, start=selected_dir)
				out_dir = os.path.join(_out_dir, rel_p)
			ovl.extract(out_dir, only_types=only_types)

	def inject_ask(self):
		files = QtWidgets.QFileDialog.getOpenFileNames(
			self, 'Inject files', self.cfg.get("dir_inject", "C://"), self.filter)[0]
		self.inject_files(files)

	def inject_files(self, files):
		"""Tries to inject files into self.ovl_data"""
		if files:
			self.cfg["dir_inject"] = os.path.dirname(files[0])
			self.set_dirty()
			self.run_in_threadpool(self.ovl_data.add_files, (), files)
		# the gui is updated from the signal ovl.files_list emitted from add_files

	def get_replace_strings(self):
		try:
			newline = "\n"
			old = self.e_name_old.toPlainText()
			new = self.e_name_new.toPlainText()
			# make sure at least one is non-empty
			if not (old or new):
				return
			old = old.split(newline)
			new = new.split(newline)
			if len(old) != len(new):
				self.showwarning(f"Old {len(old)} and new {len(new)} must have the same amount of lines!")
			return set(zip(old, new))
		except:
			self.handle_error("Getting replace strings failed, see log!")

	def rename(self, batch=False):
		names = self.get_replace_strings()
		try:
			if names:
				for ovl in self.handle_path():
					ovl.rename(names)
					if not batch:
						self.set_dirty()
		except:
			self.handle_error("Renaming failed, see log!")

	def rename_batch(self):
		names = self.get_replace_strings()
		if names:
			try:
				for ovl in self.handle_path(batch=True):
					ovl.rename(names)
			except:
				self.handle_error("Renaming failed, see log!")

	def rename_contents(self):
		names = self.get_replace_strings()
		if names:
			# we are operating only on the current ovl, so check selection state
			only_files = self.files_container.table.get_selected_files()
			for ovl in self.handle_path():
				ovl.rename_contents(names, only_files)
				self.set_dirty()
				# file names don't change, so no need to update gui

	def rename_contents_batch(self):
		names = self.get_replace_strings()
		if names:
			only_files = ()
			for ovl in self.handle_path(batch=True):
				ovl.rename_contents(names, only_files)

	def rename_both(self):
		self.rename_contents()
		self.rename()

	def save_file_list(self):
		"""Save the OVL file list to disk"""
		if self.is_open_ovl():
			filelist_src = QtWidgets.QFileDialog.getSaveFileName(
				self, 'Save File List',
				os.path.join(self.cfg.get("dir_extract", "C://"), self.file_widget.filename + ".files.txt"),
				"Txt file (*.txt)", )[0]
			if filelist_src:
				try:
					file_names = self.files_container.table.get_files()
					with open(filelist_src, 'w') as f:
						f.write("\n".join(file_names))

					self.set_msg_temporarily("Saved file list")
				except:
					self.handle_error("Writing file list failed, see log!")

	def save_included_ovls(self):
		"""Save the OVL include list to disk"""
		if self.is_open_ovl():
			filepath = QtWidgets.QFileDialog.getSaveFileName(
				self, 'Save ovls.include', os.path.join(self.cfg.get("dir_extract", "C://"), "ovls.include"),
				"Include file (*.include)", )[0]
			if filepath:
				try:
					self.ovl_data.save_included_ovls(filepath)
					self.set_msg_temporarily("Saved included OVLs")
				except:
					self.handle_error("Writing included OVLs failed, see log!")

	def load_included_ovls(self):
		filepath = QtWidgets.QFileDialog.getOpenFileName(
			self, "Open ovls.include", os.path.join(self.cfg.get("dir_inject", "C://"), "ovls.include"),
				"Include file (*.include)", )[0]
		if filepath:
			try:
				self.ovl_data.load_included_ovls(filepath)
				self.set_dirty()
				self.set_msg_temporarily("Loaded included OVLs")
			except:
				self.handle_error("Opening included OVLs failed, see log!")

	def remove(self):
		if self.is_open_ovl() and self.files_container.table.hasFocus():
			selected_file_names = self.files_container.table.get_selected_files()
			if selected_file_names:
				try:
					self.ovl_data.remove(selected_file_names)
					self.set_dirty()
				except:
					self.handle_error("Removing file from OVL failed, see log!")

	def ask_game_root(self):
		return QtWidgets.QFileDialog.getExistingDirectory(
			self, 'Game Root folder', self.cfg.get("dir_ovls_in", "C://"))

	def game_root(self):
		if self.installed_games.get_root().endswith("ovldata"):
			return self.installed_games.get_root()
		return ""
	
	def walk_root(self):
		# todo - fall back on game root if selected dir is not child of current game dir
		selected = self.installed_games.get_selected_dir()
		return selected if selected else self.game_root()

	def walker_hash(self, ):
		self.run_in_threadpool(walker.generate_hash_table, (), self, self.game_root())

	def walker_fgm(self, ):
		dialog = widgets.WalkerDialog(self, "Inspect FGMs", self.walk_root())
		chk_full_report = widgets.QCheckBox("Full Report")
		chk_full_report.setChecked(self.walk_root() == self.game_root())
		dialog.options.addWidget(chk_full_report)
		if dialog.exec():
			self.run_in_threadpool(walker.get_fgm_values, (), self, self.game_root(),
				walk_dir=dialog.walk_dir, walk_ovls=dialog.chk_ovls.isChecked(),
				official_only=dialog.chk_official.isChecked(), full_report=chk_full_report.isChecked()
			)

	def walker_manis(self, ):
		dialog = widgets.WalkerDialog(self, "Inspect Manis", self.walk_root())
		if dialog.exec():
			self.run_in_threadpool(walker.get_manis_values, (), self, dialog.walk_dir,
				walk_ovls=dialog.chk_ovls.isChecked(), official_only=dialog.chk_official.isChecked()
			)

	def inspect_models(self):
		dialog = widgets.WalkerDialog(self, "Inspect Models", self.walk_root())
		if dialog.exec():
			self.run_in_threadpool(walker.bulk_test_models, (), self, dialog.walk_dir,
				walk_ovls=dialog.chk_ovls.isChecked(), official_only=dialog.chk_official.isChecked()
			)


if __name__ == '__main__':
	startup(MainWindow, GuiOptions(log_name="ovl_tool_gui"))
