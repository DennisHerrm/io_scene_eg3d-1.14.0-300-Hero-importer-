# SPDX-License-Identifier: GPL-3.0-or-later
"""Logging for the EG3D importer.

Three sinks, all optional and independent:
  * the system console  (Window > Toggle System Console on Windows)
  * a Text data block inside the .blend  (Scripting workspace)
  * a .log file next to the imported .model

Levels: ERROR < WARN < INFO < DEBUG < TRACE
"""

import os
import time

LEVELS = {"ERROR": 0, "WARN": 1, "INFO": 2, "DEBUG": 3, "TRACE": 4}


class Logger(object):
    def __init__(self, level="INFO", to_console=True, to_text=None,
                 to_file=None, prefix="EG3D"):
        self.level = LEVELS.get(str(level).upper(), 2)
        self.to_console = to_console
        self.prefix = prefix
        self.lines = []
        self.counts = {k: 0 for k in LEVELS}
        self.t0 = time.time()
        self._text = to_text
        self._fh = None
        if to_file:
            try:
                self._fh = open(to_file, "w", encoding="utf-8")
                self.file_path = to_file
            except OSError as exc:
                self._fh = None
                self.file_path = None
                print("[%s][WARN ] cannot open log file %s: %s"
                      % (prefix, to_file, exc))
        else:
            self.file_path = None

    # -- internals ---------------------------------------------------------
    def _emit(self, lvl, fmt, args):
        self.counts[lvl] = self.counts.get(lvl, 0) + 1
        if LEVELS[lvl] > self.level:
            return
        try:
            msg = fmt % args if args else str(fmt)
        except Exception:
            msg = "%s %r" % (fmt, args)
        line = "[%7.3fs][%-5s] %s" % (time.time() - self.t0, lvl, msg)
        self.lines.append(line)
        if self.to_console:
            print("[%s]%s" % (self.prefix, line))
        if self._fh:
            try:
                self._fh.write(line + "\n")
            except Exception:
                pass

    # -- public ------------------------------------------------------------
    def error(self, fmt, *a):
        self._emit("ERROR", fmt, a)

    def warn(self, fmt, *a):
        self._emit("WARN", fmt, a)

    def info(self, fmt, *a):
        self._emit("INFO", fmt, a)

    def debug(self, fmt, *a):
        self._emit("DEBUG", fmt, a)

    def trace(self, fmt, *a):
        self._emit("TRACE", fmt, a)

    def rule(self, title=""):
        self.info("%s", ("--- %s " % title).ljust(74, "-") if title else "-" * 74)

    def summary(self):
        return ("%d errors, %d warnings, %d lines, %.2fs"
                % (self.counts.get("ERROR", 0), self.counts.get("WARN", 0),
                   len(self.lines), time.time() - self.t0))

    def close(self, text_name=None):
        if self._fh:
            try:
                self._fh.write("\n%s\n" % self.summary())
                self._fh.close()
            except Exception:
                pass
            self._fh = None
        if text_name:
            try:
                import bpy
                txt = bpy.data.texts.get(text_name)
                if txt is None:
                    txt = bpy.data.texts.new(text_name)
                txt.clear()
                txt.write("\n".join(self.lines))
                txt.write("\n\n" + self.summary() + "\n")
            except Exception as exc:
                print("[%s] could not write text block: %s" % (self.prefix, exc))


def default_log_path(model_path):
    base, _ = os.path.splitext(model_path)
    return base + "_eg3d_import.log"
