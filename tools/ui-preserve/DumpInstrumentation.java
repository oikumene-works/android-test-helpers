package qa.capture.preserve;

import android.app.Instrumentation;
import android.app.UiAutomation;
import android.graphics.Rect;
import android.os.Bundle;
import android.os.SystemClock;
import android.util.Xml;
import android.view.accessibility.AccessibilityNodeInfo;
import java.io.File;
import java.io.FileOutputStream;
import java.io.StringWriter;
import java.nio.charset.StandardCharsets;
import org.xmlpull.v1.XmlSerializer;

/** Prototype: never connects with default flags or calls stock uiautomator. */
public class DumpInstrumentation extends Instrumentation {
    private Bundle args;
    private int nodes;
    public void onCreate(Bundle arguments) {
        super.onCreate(arguments);
        args = arguments == null ? new Bundle() : arguments;
        start();
    }
    public void onStart() {
        Bundle result = new Bundle();
        UiAutomation automation = null;
        File output = null;
        boolean created = false;
        int code = 1;
        try {
            String id = args.getString("capture_id");
            String expected = args.getString("expected_package");
            if (id == null || !id.matches("[0-9a-f]{32}")) throw new IllegalArgumentException("Invalid capture_id");
            if (expected == null || !expected.matches("[A-Za-z0-9_.]+")) throw new IllegalArgumentException("Invalid expected_package");
            output = new File(getTargetContext().getFilesDir(), "tree-" + id + ".xml");
            if (output.exists()) throw new IllegalStateException("Output already exists");
            automation = getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);
            if (automation == null) throw new IllegalStateException("UiAutomation connection failed");
            long connected = SystemClock.uptimeMillis();
            // Bounded test hook to verify host timeout cleanup, not a normal capture delay.
            int hold = Integer.parseInt(args.getString("test_hold_ms", "0"));
            if (hold < 0 || hold > 10000) throw new IllegalArgumentException("Invalid test_hold_ms");
            if (hold > 0) SystemClock.sleep(hold);
            AccessibilityNodeInfo root = null;
            for (int attempt = 0; attempt < 3 && root == null; attempt++) {
                root = automation.getRootInActiveWindow();
                if (root == null) SystemClock.sleep(100);
            }
            if (root == null) throw new IllegalStateException("No active root");
            StringWriter buffer = new StringWriter();
            try {
                if (!expected.contentEquals(root.getPackageName() == null ? "" : root.getPackageName()))
                    throw new IllegalStateException("Unexpected active package");
                XmlSerializer xml = Xml.newSerializer();
                xml.setOutput(buffer);
                xml.startDocument("UTF-8", true);
                xml.startTag(null, "hierarchy");
                xml.attribute(null, "capture_id", id);
                xml.attribute(null, "connected_uptime_ms", Long.toString(connected));
                xml.attribute(null, "capture_uptime_ms", Long.toString(SystemClock.uptimeMillis()));
                xml.attribute(null, "connection_flags", "1");
                writeNode(xml, root, 0);
                xml.endTag(null, "hierarchy");
                xml.endDocument();
            } finally { root.recycle(); }
            if (nodes == 0) throw new IllegalStateException("Empty tree");
            created = output.createNewFile();
            if (!created) throw new IllegalStateException("Output already exists");
            try (FileOutputStream stream = new FileOutputStream(output)) {
                stream.write(buffer.toString().getBytes(StandardCharsets.UTF_8));
                stream.getFD().sync();
            }
            result.putString("file", output.getName());
            result.putInt("nodes", nodes);
            result.putLong("connected_uptime_ms", connected);
            result.putLong("finished_uptime_ms", SystemClock.uptimeMillis());
            code = -1;
        } catch (Exception error) {
            result.putString("error", error.toString());
            if (created && output != null) output.delete();
        } finally {
            // Instrumentation.finish() closes its UiAutomation connection.
            finish(code, result);
        }
    }
    private void writeNode(XmlSerializer xml, AccessibilityNodeInfo node, int depth) throws Exception {
        if (depth > 80 || ++nodes > 10000) throw new IllegalStateException("Tree limit exceeded");
        xml.startTag(null, "node");
        attribute(xml, "package", node.getPackageName());
        attribute(xml, "class", node.getClassName());
        attribute(xml, "text", node.getText());
        attribute(xml, "content-desc", node.getContentDescription());
        attribute(xml, "resource-id", node.getViewIdResourceName());
        Rect bounds = new Rect(); node.getBoundsInScreen(bounds);
        xml.attribute(null, "bounds", bounds.toShortString());
        xml.attribute(null, "clickable", Boolean.toString(node.isClickable()));
        xml.attribute(null, "scrollable", Boolean.toString(node.isScrollable()));
        for (int i = 0; i < node.getChildCount(); i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                try { writeNode(xml, child, depth + 1); } finally { child.recycle(); }
            }
        }
        xml.endTag(null, "node");
    }
    private void attribute(XmlSerializer xml, String name, CharSequence value) throws Exception {
        xml.attribute(null, name, value == null ? "" : value.toString());
    }
}
