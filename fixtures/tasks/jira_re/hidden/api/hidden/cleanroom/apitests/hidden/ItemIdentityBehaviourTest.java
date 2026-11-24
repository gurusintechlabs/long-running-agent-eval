package cleanroom.apitests.hidden;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.almworks.jira.structure.api.item.CoreIdentities;
import com.almworks.jira.structure.api.item.CoreItemTypes;
import com.almworks.jira.structure.api.item.ItemIdentity;
import java.text.ParseException;
import org.junit.jupiter.api.Test;

/** Item identities: a type plus a numeric or a text id (hidden API tier, phase JA1). */
class ItemIdentityBehaviourTest {

    private static String repeat(char c, int n) {
        StringBuilder b = new StringBuilder();
        for (int i = 0; i < n; i++) {
            b.append(c);
        }
        return b.toString();
    }

    @Test
    void numericAndTextIdsHaveDistinctTextForms() {
        assertEquals("t/42", ItemIdentity.longId("t", 42).toString());
        assertEquals("t//abc", ItemIdentity.stringId("t", "abc").toString());
    }

    @Test
    void accessorsMatchTheKindOfId() {
        ItemIdentity n = ItemIdentity.longId("t", 7);
        ItemIdentity s = ItemIdentity.stringId("t", "x");
        assertTrue(n.isLongId());
        assertFalse(n.isStringId());
        assertEquals(7, n.getLongId());
        assertEquals("t", n.getItemType());
        assertTrue(s.isStringId());
        assertEquals("x", s.getStringId());
        assertThrows(UnsupportedOperationException.class, n::getStringId);
        assertThrows(UnsupportedOperationException.class, s::getLongId);
    }

    @Test
    void parsesBothFormsBack() throws ParseException {
        assertEquals(ItemIdentity.longId("t", 42), ItemIdentity.parse("t/42"));
        assertEquals(ItemIdentity.stringId("t", "a/b"), ItemIdentity.parse("t//a/b"));
        assertEquals(ItemIdentity.longId("t", -3), ItemIdentity.parse("t/-3"));
    }

    @Test
    void aBareNumberIsAnIssue() throws ParseException {
        assertEquals(CoreIdentities.issue(10200), ItemIdentity.parse("10200"));
        assertEquals(CoreItemTypes.ISSUE, ItemIdentity.parse("10200").getItemType());
    }

    @Test
    void malformedTextIsAParseError() {
        for (String bad : new String[] {null, "", "abc", "/5", "t/", "t//", "t/x", "t/1.5"}) {
            assertThrows(ParseException.class, () -> ItemIdentity.parse(bad), String.valueOf(bad));
        }
    }

    @Test
    void identityIsByTypeAndId() {
        assertEquals(ItemIdentity.longId("t", 1), ItemIdentity.longId("t", 1));
        assertEquals(ItemIdentity.longId("t", 1).hashCode(), ItemIdentity.longId("t", 1).hashCode());
        assertNotEquals(ItemIdentity.longId("t", 1), ItemIdentity.longId("u", 1));
        assertNotEquals(ItemIdentity.longId("t", 1), ItemIdentity.stringId("t", "1"));
        assertEquals(ItemIdentity.stringId("t", "a"), ItemIdentity.stringId("t", "a"));
    }

    @Test
    void typesAndTextIdsAreLimitedTo190Characters() {
        ItemIdentity.longId(repeat('t', 190), 1);
        ItemIdentity.stringId("t", repeat('x', 190));
        assertThrows(IllegalArgumentException.class, () -> ItemIdentity.longId(repeat('t', 191), 1));
        assertThrows(IllegalArgumentException.class, () -> ItemIdentity.stringId("t", repeat('x', 191)));
    }

    @Test
    void blankTextIdsAreRejected() {
        assertThrows(IllegalArgumentException.class, () -> ItemIdentity.stringId("t", ""));
        assertThrows(IllegalArgumentException.class, () -> ItemIdentity.stringId("t", "  "));
    }

    @Test
    void theSimplifiedFormDropsTheStandardTypePrefix() {
        assertEquals("issue/5", CoreIdentities.issue(5).toSimplifiedString());
        assertEquals("t//a", ItemIdentity.stringId("t", "a").toSimplifiedString());
        assertEquals(CoreItemTypes.STANDARD_TYPE_PREFIX + "issue/5", CoreIdentities.issue(5).toString());
    }

    @Test
    void itemZeroIsANumericIdOfTypeZero() {
        assertEquals(ItemIdentity.longId("0", 0), ItemIdentity.ITEM_ZERO);
    }
}
