#!/usr/bin/osascript

on run argv
	set AppleScript's text item delimiters to " "
	tell application "Terminal"
		do script # Open a new window
		activate
		do script "exec " & (argv as string) in window 1
	end tell
end run
