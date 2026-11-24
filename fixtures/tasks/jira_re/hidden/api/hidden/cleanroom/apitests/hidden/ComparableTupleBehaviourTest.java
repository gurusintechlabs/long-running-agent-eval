package cleanroom.apitests.hidden;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.almworks.jira.structure.api.util.ComparableTuple;
import java.util.Arrays;
import java.util.Collections;
import org.junit.jupiter.api.Test;

/** Sort keys made of numbers and strings (hidden API tier, phase JA1). */
class ComparableTupleBehaviourTest {

    @Test
    void comparesElementByElement() {
        assertTrue(ComparableTuple.of(1, 2).compareTo(ComparableTuple.of(1, 3)) < 0);
        assertTrue(ComparableTuple.of("b", "a").compareTo(ComparableTuple.of("a", "z")) > 0);
        assertEquals(0, ComparableTuple.of("a", 5).compareTo(ComparableTuple.of("a", 5)));
    }

    @Test
    void numbersSortBeforeStrings() {
        assertTrue(ComparableTuple.of(999).compareTo(ComparableTuple.of("0")) < 0);
        assertTrue(ComparableTuple.of("0").compareTo(ComparableTuple.of(-5)) > 0);
    }

    @Test
    void aShorterPrefixSortsFirst() {
        assertTrue(ComparableTuple.of("a").compareTo(ComparableTuple.of("a", "b")) < 0);
        assertTrue(ComparableTuple.NIL.compareTo(ComparableTuple.of(0)) < 0);
    }

    @Test
    void wholeAndFractionalNumbersCompareByValue() {
        assertEquals(ComparableTuple.of(2L), ComparableTuple.of(2.0));
        assertEquals(ComparableTuple.of(2L).hashCode(), ComparableTuple.of(2.0).hashCode());
        assertTrue(ComparableTuple.of(2.5).compareTo(ComparableTuple.of(2L)) > 0);
        assertTrue(ComparableTuple.of(2.5).compareTo(ComparableTuple.of(3L)) < 0);
    }

    @Test
    void aListFlattensNestedTuples() {
        ComparableTuple t = ComparableTuple.of(Arrays.asList("a", ComparableTuple.of(1, 2), 3L));
        assertEquals(ComparableTuple.of(Arrays.asList("a", 1L, 2L, 3L)), t);
        assertEquals("('a',1,2,3)", t.toString());
    }

    @Test
    void nullsAndOtherTypesAreRejected() {
        assertThrows(IllegalArgumentException.class, () -> ComparableTuple.of((String) null));
        assertThrows(IllegalArgumentException.class, () -> ComparableTuple.of("a", (String) null));
        assertThrows(IllegalArgumentException.class, () -> ComparableTuple.of((java.util.List<?>) null));
        assertThrows(IllegalArgumentException.class, () -> ComparableTuple.of(Collections.singletonList(new Object())));
        assertThrows(IllegalArgumentException.class, () -> ComparableTuple.of(Arrays.asList("a", null)));
    }

    @Test
    void textFormQuotesStrings() {
        assertEquals("('x',7,'y')", ComparableTuple.of("x", 7, "y").toString());
        assertEquals("()", ComparableTuple.NIL.toString());
    }

    @Test
    void arraysAreCopied() {
        String[] parts = {"a", "b"};
        ComparableTuple t = ComparableTuple.of(parts);
        parts[0] = "z";
        assertEquals(ComparableTuple.of("a", "b"), t);
    }
}
