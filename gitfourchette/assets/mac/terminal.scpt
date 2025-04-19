#!/usr/bin/env osascript -l JavaScript

function run(argv) {
	var terminal = Application("Terminal");
	terminal.activate();
	var tab = terminal.doScript();  // Open new tab
	terminal.doScript("exec " + argv.join(" "), { in: tab });
}
