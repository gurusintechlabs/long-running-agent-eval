package cleanroom.apitests.hidden;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.almworks.integers.IntArray;
import com.almworks.integers.LongArray;
import com.almworks.jira.structure.api.error.StructureException;
import com.almworks.jira.structure.api.forest.raw.ArrayForest;
import com.almworks.jira.structure.api.forest.raw.Forest;
import com.almworks.jira.structure.api.util.La;
import org.junit.jupiter.api.Test;

/** The public forest: an ordered list of rows, each with a depth (hidden API tier, phase JA1). */
class ForestBehaviourTest {

    /** 1 [2 [3], 4], 5 */
    private static ArrayForest sample() {
        return forest(new long[] {1, 2, 3, 4, 5}, new int[] {0, 1, 2, 1, 0});
    }

    private static ArrayForest forest(long[] rows, int[] depths) {
        return new ArrayForest(new LongArray(rows), new IntArray(depths));
    }

    private static void assertForest(Forest f, long[] rows, int[] depths) {
        assertArrayEquals(rows, f.getRows().toNativeArray(), f.toFullString());
        assertArrayEquals(depths, f.getDepths().toNativeArray(), f.toFullString());
    }

    private static La<Long, Boolean> not(long row) {
        return La.adapt(r -> r != row);
    }

    @Test
    void navigatesParentsChildrenAndRoots() {
        ArrayForest f = sample();
        assertEquals(5, f.size());
        assertEquals(2, f.getParent(3));
        assertEquals(0, f.getParent(1));
        assertEquals(0, f.getParent(99));
        assertArrayEquals(new long[] {1, 5}, f.getRoots().toNativeArray());
        assertArrayEquals(new long[] {2, 4}, f.getChildren(1).toNativeArray());
        assertArrayEquals(new long[] {}, f.getChildren(3).toNativeArray());
        assertEquals(4, f.getLastChild(1));
        assertArrayEquals(new long[] {1, 2, 3}, f.getPath(3).toNativeArray());
    }

    @Test
    void indexesAndSubtreeEnds() {
        ArrayForest f = sample();
        assertEquals(2, f.indexOf(3));
        assertEquals(-1, f.indexOf(99));
        assertEquals(-1, f.indexOf(0));
        assertTrue(f.containsRow(4));
        assertFalse(f.containsRow(99));
        assertEquals(4, f.getSubtreeEnd(0));       // row 1 spans indexes 0..3
        assertEquals(3, f.getSubtreeEnd(1));       // row 2 spans 1..2
        assertEquals(5, f.getSubtreeEnd(4));
        assertEquals(0, f.getParentIndex(1));
        assertEquals(-1, f.getParentIndex(0));
    }

    @Test
    void siblings() {
        ArrayForest f = sample();
        assertEquals(2, f.getPrecedingSibling(4));
        assertEquals(0, f.getPrecedingSibling(2));
        assertEquals(4, f.getNextSibling(2));
        assertEquals(0, f.getNextSibling(4));
        assertEquals(5, f.getNextSibling(1));
    }

    @Test
    void addsARowUnderAParentAfterASibling() throws StructureException {
        ArrayForest f = sample();
        assertTrue(f.addRow(6, 1, 2));               // after 2's whole subtree, still under 1
        assertForest(f, new long[] {1, 2, 3, 6, 4, 5}, new int[] {0, 1, 2, 1, 1, 0});
        assertTrue(f.addRow(7, 0, 0));               // no parent, no sibling: the first root
        assertEquals(7, f.getRow(0));
        assertEquals(0, f.getDepth(0));
    }

    @Test
    void anAfterThatIsNotAChildOfTheParentIsIgnored() throws StructureException {
        ArrayForest f = sample();
        f.addRow(6, 1, 5);                           // 5 is not under 1: insert as 1's first child
        assertForest(f, new long[] {1, 6, 2, 3, 4, 5}, new int[] {0, 1, 1, 2, 1, 0});
    }

    @Test
    void anUnknownParentIsAnError() {
        ArrayForest f = sample();
        assertThrows(StructureException.class, () -> f.addRow(6, 99, 0));
    }

    @Test
    void rowZeroIsNeverAdded() throws StructureException {
        ArrayForest f = sample();
        assertFalse(f.addRow(0, 0, 0));
        assertEquals(5, f.size());
    }

    @Test
    void addingAPresentRowMovesItsSubtree() throws StructureException {
        ArrayForest f = sample();
        assertTrue(f.addRow(2, 5, 0));
        assertForest(f, new long[] {1, 4, 5, 2, 3}, new int[] {0, 1, 0, 1, 2});
    }

    @Test
    void movesASubtree() throws StructureException {
        ArrayForest f = sample();
        assertTrue(f.moveSubtree(4, 0, 5));          // to the top level, after 5
        assertForest(f, new long[] {1, 2, 3, 5, 4}, new int[] {0, 1, 2, 0, 0});
        assertFalse(f.moveSubtree(99, 0, 0));
    }

    @Test
    void aRowCannotMoveUnderItsOwnDescendant() {
        ArrayForest f = sample();
        assertThrows(StructureException.class, () -> f.moveSubtree(1, 3, 0));
    }

    @Test
    void removesASubtreeAndReturnsIt() {
        ArrayForest f = sample();
        Forest removed = f.removeSubtree(2);
        assertForest(removed, new long[] {2, 3}, new int[] {0, 1});
        assertForest(f, new long[] {1, 4, 5}, new int[] {0, 1, 0});
        assertTrue(f.removeSubtree(99).isEmpty());
    }

    @Test
    void filterLiftsTheChildrenOfRejectedRows() {
        Forest f = sample().filter(not(2));
        assertForest(f, new long[] {1, 3, 4, 5}, new int[] {0, 1, 1, 0});
    }

    @Test
    void filterHardestDropsWholeSubtrees() {
        Forest f = sample().filterHardest(not(2));
        assertForest(f, new long[] {1, 4, 5}, new int[] {0, 1, 0});
    }

    @Test
    void filterSoftKeepsTheAncestorsOfAcceptedRows() {
        Forest f = sample().filterSoft(La.adapt(r -> r == 3L));
        assertForest(f, new long[] {1, 2, 3}, new int[] {0, 1, 2});
    }

    @Test
    void aNullFilterKeepsEverything() {
        ArrayForest f = sample();
        assertEquals(f, f.filter(null));
        assertEquals(f, f.filterHardest(null));
    }

    @Test
    void subtreesAreCopiedWithRebasedDepths() {
        Forest sub = sample().subtree(2);
        assertForest(sub, new long[] {2, 3}, new int[] {0, 1});
        assertTrue(sample().subtree(99).isEmpty());
    }

    @Test
    void rowIdsZeroAndMinusOneAreRejected() {
        assertThrows(IllegalArgumentException.class, () -> forest(new long[] {1, 0}, new int[] {0, 1}));
        assertThrows(IllegalArgumentException.class, () -> forest(new long[] {-1}, new int[] {0}));
    }

    @Test
    void immutableForestsRefuseChanges() {
        ArrayForest f = sample().makeImmutable();
        assertTrue(f.isImmutable());
        assertThrows(UnsupportedOperationException.class, () -> f.addRow(6, 0, 0));
        assertThrows(UnsupportedOperationException.class, () -> f.removeSubtree(2));
        assertFalse(f.copy().isImmutable());
        assertTrue(Forest.EMPTY.isEmpty() && Forest.EMPTY.isImmutable());
    }

    @Test
    void equalityIsByRowsAndDepths() {
        assertEquals(sample(), sample());
        assertEquals(sample().hashCode(), sample().hashCode());
        assertNotEquals(sample(), forest(new long[] {1, 2, 3, 4, 5}, new int[] {0, 1, 1, 1, 0}));
    }

    @Test
    void textFormListsRowColonDepth() {
        assertEquals("forest(1:0,2:1,3:2,4:1,5:0)", sample().toString());
        assertEquals("forest(ro,1:0,2:1,3:2,4:1,5:0)", sample().makeImmutable().toString());
        assertEquals("forest()", new ArrayForest().toString());
    }

    @Test
    void longForestsAreAbbreviatedButNotInTheFullForm() {
        long[] rows = new long[25];
        int[] depths = new int[25];
        for (int i = 0; i < 25; i++) {
            rows[i] = i + 1;
        }
        ArrayForest f = forest(rows, depths);
        assertTrue(f.toString().endsWith(",20:0 ... [25])"), f.toString());
        assertTrue(f.toFullString().endsWith(",25:0)"), f.toFullString());
    }
}
