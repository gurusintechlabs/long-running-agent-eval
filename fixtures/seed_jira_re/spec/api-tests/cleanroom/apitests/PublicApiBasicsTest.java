package cleanroom.apitests;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.almworks.integers.IntArray;
import com.almworks.integers.LongArray;
import com.almworks.jira.structure.api.error.StructureException;
import com.almworks.jira.structure.api.forest.raw.ArrayForest;
import com.almworks.jira.structure.api.item.ItemIdentity;
import com.almworks.jira.structure.api.util.ComparableTuple;
import java.text.ParseException;
import org.junit.jupiter.api.Test;

/**
 * A few behaviours of the public API, from spec/SPEC.md. The full set the replacement is measured against is
 * larger. Copy this directory into src/test/java; these tests must pass unchanged.
 */
class PublicApiBasicsTest {

    @Test
    void itemIdentityTextFormsRoundTrip() throws ParseException {
        ItemIdentity n = ItemIdentity.longId("t", 42);
        ItemIdentity s = ItemIdentity.stringId("t", "abc");
        assertEquals("t/42", n.toString());
        assertEquals("t//abc", s.toString());
        assertEquals(n, ItemIdentity.parse(n.toString()));
        assertEquals(s, ItemIdentity.parse(s.toString()));
    }

    @Test
    void itemIdentityRejectsAnEmptyId() {
        assertThrows(ParseException.class, () -> ItemIdentity.parse(""));
    }

    @Test
    void forestNavigation() {
        // 10 [20, 30], 40
        ArrayForest f = new ArrayForest(new LongArray(new long[] {10, 20, 30, 40}), new IntArray(new int[] {0, 1, 1, 0}));
        assertEquals(10, f.getParent(30));
        assertArrayEquals(new long[] {20, 30}, f.getChildren(10).toNativeArray());
        assertArrayEquals(new long[] {10, 40}, f.getRoots().toNativeArray());
    }

    @Test
    void forestAddRowAtTheTopLevel() throws StructureException {
        ArrayForest f = new ArrayForest(new LongArray(new long[] {10}), new IntArray(new int[] {0}));
        assertTrue(f.addRow(20, 0, 10));
        assertEquals("forest(10:0,20:0)", f.toString());
    }

    @Test
    void tuplesOrderNumbersBeforeStrings() {
        assertTrue(ComparableTuple.of(5).compareTo(ComparableTuple.of("a")) < 0);
    }
}
