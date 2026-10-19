package qa;

import com.android.uiautomator.core.Configurator;
import com.android.uiautomator.testrunner.UiAutomatorTestCase;
import java.io.File;

/** Bounded fallback for a changing screen that never reaches UI idle. */
public class NoIdleDump extends UiAutomatorTestCase {
    public void testDump() throws Exception {
        String output = getParams().getString("output");
        if (output == null || !output.matches("fdroid-phase-[0-9a-f]{32}/fallback\\.xml")) {
            throw new IllegalArgumentException("Expected this capture's unique relative output path");
        }
        File target = new File("/data/local/tmp", output);
        if (!target.getParentFile().isDirectory() || target.exists()) {
            throw new IllegalStateException("Output must be new and its directory must already exist");
        }
        Configurator.getInstance().setWaitForIdleTimeout(0);
        for (int attempt = 0; attempt < 3; attempt++) {
            sleep(300);
            getUiDevice().dumpWindowHierarchy(output);
            if (target.isFile()) return;
        }
        throw new IllegalStateException("No current accessibility hierarchy produced after three attempts");
        // The caller checks XML structure and rejects an empty hierarchy; no retry of an existing file.
    }
}
