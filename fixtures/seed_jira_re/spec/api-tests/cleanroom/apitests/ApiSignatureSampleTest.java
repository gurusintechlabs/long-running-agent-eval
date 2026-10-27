package cleanroom.apitests;

import static org.junit.jupiter.api.Assertions.assertTrue;

import java.lang.reflect.Constructor;
import java.lang.reflect.Field;
import java.lang.reflect.Member;
import java.lang.reflect.Method;
import java.lang.reflect.Modifier;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.Set;
import java.util.TreeSet;
import org.junit.jupiter.api.Test;

/**
 * The exact signatures of a sample of public API types, as spec/SPEC.md lists them (generated). The
 * replacement is measured against every public type. Copy this directory into src/test/java; these tests
 * must pass unchanged.
 *
 * Member lines read: kind, modifiers (sorted), then name and JVM descriptor (fields: name:type).
 */
class ApiSignatureSampleTest {

    private static String desc(Class<?> c) {
        if (c.isArray()) {
            return "[" + desc(c.getComponentType());
        }
        if (c.isPrimitive()) {
            return c == void.class ? "V" : c == boolean.class ? "Z" : c == byte.class ? "B" : c == char.class ? "C"
                    : c == short.class ? "S" : c == int.class ? "I" : c == long.class ? "J" : c == float.class ? "F" : "D";
        }
        return "L" + c.getName().replace('.', '/') + ";";
    }

    private static String params(Class<?>[] types) {
        StringBuilder b = new StringBuilder("(");
        for (Class<?> t : types) {
            b.append(desc(t));
        }
        return b.append(")").toString();
    }

    private static String access(int m) {
        return Modifier.isPublic(m) ? "public" : Modifier.isProtected(m) ? "protected" : null;
    }

    private static String line(String kind, Set<String> flags, String key) {
        return kind + " " + String.join(" ", flags) + " " + key;
    }

    private static Set<String> surface(Class<?> c) {
        Set<String> out = new TreeSet<>();
        boolean iface = c.isInterface();
        String kind = c.isAnnotation() ? "annotation" : iface ? "interface" : c.isEnum() ? "enum" : "class";
        Set<String> tf = new TreeSet<>();
        tf.add(String.valueOf(access(c.getModifiers())));
        if (kind.equals("class") && Modifier.isAbstract(c.getModifiers())) {
            tf.add("abstract");
        }
        if (kind.equals("class") && Modifier.isFinal(c.getModifiers())) {
            tf.add("final");
        }
        if (kind.equals("class") && c.getEnclosingClass() != null && Modifier.isStatic(c.getModifiers())) {
            tf.add("static");
        }
        out.add(line("type", tf, kind));
        if (!iface && c.getSuperclass() != null) {
            out.add("extends " + c.getSuperclass().getName());
        }
        for (Class<?> i : c.getInterfaces()) {
            out.add("implements " + i.getName());
        }
        for (Field f : c.getDeclaredFields()) {
            int m = f.getModifiers();
            if (f.isSynthetic() || access(m) == null) {
                continue;
            }
            Set<String> fl = new TreeSet<>();
            fl.add(access(m));
            if (Modifier.isStatic(m)) {
                fl.add("static");
            }
            if (Modifier.isFinal(m)) {
                fl.add("final");
            }
            out.add(line("field", fl, f.getName() + ":" + desc(f.getType())));
        }
        List<Member> callables = new ArrayList<>(Arrays.asList(c.getDeclaredMethods()));
        callables.addAll(Arrays.asList(c.getDeclaredConstructors()));
        for (Member x : callables) {
            int m = x.getModifiers();
            boolean ctor = x instanceof Constructor;
            if (x.isSynthetic() || (!ctor && ((Method) x).isBridge()) || access(m) == null) {
                continue;
            }
            Set<String> fl = new TreeSet<>();
            fl.add(access(m));
            if (Modifier.isStatic(m)) {
                fl.add("static");
            }
            if (Modifier.isAbstract(m)) {
                fl.add("abstract");
            }
            if (ctor ? ((Constructor<?>) x).isVarArgs() : ((Method) x).isVarArgs()) {
                fl.add("varargs");
            }
            if (Modifier.isFinal(m) && !iface) {
                fl.add("final");
            }
            if (iface && !Modifier.isAbstract(m) && !Modifier.isStatic(m)) {
                fl.add("default");
            }
            String key = ctor ? "<init>" + params(((Constructor<?>) x).getParameterTypes()) + "V"
                    : x.getName() + params(((Method) x).getParameterTypes()) + desc(((Method) x).getReturnType());
            out.add(line("method", fl, key));
        }
        return out;
    }

    private static void assertSurface(String type, String... expected) {
        Class<?> c;
        try {
            c = Class.forName(type, false, ApiSignatureSampleTest.class.getClassLoader());
        } catch (ClassNotFoundException e) {
            throw new AssertionError(type + " does not exist");
        }
        Set<String> got = surface(c);
        List<String> missing = new ArrayList<>();
        for (String e : expected) {
            if (!got.contains(e)) {
                missing.add(e);
            }
        }
        assertTrue(missing.isEmpty(), type + ": missing or different:\n  " + String.join("\n  ", missing));
    }

    @Test
    void itemIdentity() {
        assertSurface("com.almworks.jira.structure.api.item.ItemIdentity",
                "extends java.lang.Object",
                "field final public static ITEM_ZERO:Lcom/almworks/jira/structure/api/item/ItemIdentity;",
                "implements java.io.Serializable",
                "method abstract public toSimplifiedString()Ljava/lang/String;",
                "method public getItemType()Ljava/lang/String;",
                "method public getLongId()J",
                "method public getStringId()Ljava/lang/String;",
                "method public isLongId()Z",
                "method public isStringId()Z",
                "method public static longId(Ljava/lang/String;J)Lcom/almworks/jira/structure/api/item/ItemIdentity;",
                "method public static parse(Ljava/lang/String;)Lcom/almworks/jira/structure/api/item/ItemIdentity;",
                "method public static stringId(Ljava/lang/String;Ljava/lang/String;)Lcom/almworks/jira/structure/api/item/ItemIdentity;",
                "type abstract public class");
    }

    @Test
    void itemIdentityLongIdentity() {
        assertSurface("com.almworks.jira.structure.api.item.ItemIdentity$LongIdentity",
                "extends com.almworks.jira.structure.api.item.ItemIdentity",
                "implements java.io.Serializable",
                "method public equals(Ljava/lang/Object;)Z",
                "method public getLongId()J",
                "method public hashCode()I",
                "method public isLongId()Z",
                "method public toSimplifiedString()Ljava/lang/String;",
                "method public toString()Ljava/lang/String;",
                "type final public static class");
    }

    @Test
    void itemIdentityStringIdentity() {
        assertSurface("com.almworks.jira.structure.api.item.ItemIdentity$StringIdentity",
                "extends com.almworks.jira.structure.api.item.ItemIdentity",
                "implements java.io.Serializable",
                "method public equals(Ljava/lang/Object;)Z",
                "method public getStringId()Ljava/lang/String;",
                "method public hashCode()I",
                "method public isStringId()Z",
                "method public toSimplifiedString()Ljava/lang/String;",
                "method public toString()Ljava/lang/String;",
                "type final public static class");
    }

    @Test
    void forest() {
        assertSurface("com.almworks.jira.structure.api.forest.raw.Forest",
                "field final public static EMPTY:Lcom/almworks/jira/structure/api/forest/raw/Forest;",
                "implements com.almworks.integers.LongIntIterable",
                "method abstract public containsRow(J)Z",
                "method abstract public copy()Lcom/almworks/jira/structure/api/forest/raw/ArrayForest;",
                "method abstract public copySubforest(J)Lcom/almworks/jira/structure/api/forest/raw/ArrayForest;",
                "method abstract public copySubforestAtIndex(I)Lcom/almworks/jira/structure/api/forest/raw/ArrayForest;",
                "method abstract public filter(Lcom/almworks/jira/structure/api/util/La;)Lcom/almworks/jira/structure/api/forest/raw/Forest;",
                "method abstract public filterHardest(Lcom/almworks/jira/structure/api/util/La;)Lcom/almworks/jira/structure/api/forest/raw/Forest;",
                "method abstract public filterSoft(Lcom/almworks/jira/structure/api/util/La;)Lcom/almworks/jira/structure/api/forest/raw/Forest;",
                "method abstract public foldUpwards(Lcom/almworks/jira/structure/api/forest/raw/ForestParentChildrenClosure;)Ljava/lang/Object;",
                "method abstract public getChildren(J)Lcom/almworks/integers/LongArray;",
                "method abstract public getChildrenAtIndex(I)Lcom/almworks/integers/LongArray;",
                "method abstract public getChildrenIndicesIterator(I)Lcom/almworks/integers/IntIterator;",
                "method abstract public getDepth(I)I",
                "method abstract public getDepths()Lcom/almworks/integers/IntList;",
                "method abstract public getLastChild(J)J",
                "method abstract public getLastChildByIndex(I)J",
                "method abstract public getNextSibling(J)J",
                "method abstract public getNextSiblingForIndex(I)J",
                "method abstract public getNextSiblingIndex(I)I",
                "method abstract public getParent(J)J",
                "method abstract public getParentIndex(I)I",
                "method abstract public getParentPathForIndex(I)Lcom/almworks/integers/LongArray;",
                "method abstract public getPath(J)Lcom/almworks/integers/LongArray;",
                "method abstract public getPathForIndex(I)Lcom/almworks/integers/LongArray;",
                "method abstract public getPathIndexAtDepth(II)I",
                "method abstract public getPrecedingSibling(J)J",
                "method abstract public getPrecedingSiblingForIndex(I)J",
                "method abstract public getPrecedingSiblingIndex(I)I",
                "method abstract public getPrecedingSiblings(J)Lcom/almworks/integers/LongArray;",
                "method abstract public getPrecedingSiblingsForIndex(I)Lcom/almworks/integers/LongArray;",
                "method abstract public getRoots()Lcom/almworks/integers/LongArray;",
                "method abstract public getRow(I)J",
                "method abstract public getRows()Lcom/almworks/integers/LongList;",
                "method abstract public getSubtreeEnd(I)I",
                "method abstract public indexOf(J)I",
                "method abstract public isEmpty()Z",
                "method abstract public isImmutable()Z",
                "method abstract public scanDownwards(Lcom/almworks/jira/structure/api/forest/raw/ForestScanner;)V",
                "method abstract public size()I",
                "method abstract public subtree(J)Lcom/almworks/jira/structure/api/forest/raw/Forest;",
                "method abstract public subtreeAtIndex(I)Lcom/almworks/jira/structure/api/forest/raw/Forest;",
                "method abstract public toFullString()Ljava/lang/String;",
                "method abstract public visitParentChildrenUpwards(Lcom/almworks/jira/structure/api/forest/raw/ForestParentChildrenVisitor;)V",
                "type public interface");
    }

    @Test
    void comparableTuple() {
        assertSurface("com.almworks.jira.structure.api.util.ComparableTuple",
                "extends java.lang.Object",
                "field final public static NIL:Lcom/almworks/jira/structure/api/util/ComparableTuple;",
                "implements java.lang.Comparable",
                "method public compareTo(Lcom/almworks/jira/structure/api/util/ComparableTuple;)I",
                "method public equals(Ljava/lang/Object;)Z",
                "method public hashCode()I",
                "method public static of(D)Lcom/almworks/jira/structure/api/util/ComparableTuple;",
                "method public static of(J)Lcom/almworks/jira/structure/api/util/ComparableTuple;",
                "method public static of(JJ)Lcom/almworks/jira/structure/api/util/ComparableTuple;",
                "method public static of(Ljava/lang/String;)Lcom/almworks/jira/structure/api/util/ComparableTuple;",
                "method public static of(Ljava/lang/String;J)Lcom/almworks/jira/structure/api/util/ComparableTuple;",
                "method public static of(Ljava/lang/String;JLjava/lang/String;)Lcom/almworks/jira/structure/api/util/ComparableTuple;",
                "method public static of(Ljava/lang/String;Ljava/lang/String;)Lcom/almworks/jira/structure/api/util/ComparableTuple;",
                "method public static of(Ljava/util/List;)Lcom/almworks/jira/structure/api/util/ComparableTuple;",
                "method public static of([Ljava/lang/Long;)Lcom/almworks/jira/structure/api/util/ComparableTuple;",
                "method public static of([Ljava/lang/String;)Lcom/almworks/jira/structure/api/util/ComparableTuple;",
                "method public toString()Ljava/lang/String;",
                "type final public class");
    }

    @Test
    void structureException() {
        assertSurface("com.almworks.jira.structure.api.error.StructureException",
                "extends java.lang.Exception",
                "method protected varargs <init>(Lcom/almworks/jira/structure/api/error/StructureError;Ljava/lang/Throwable;Ljava/lang/Long;Ljava/lang/Long;Ljava/lang/Long;Lcom/almworks/jira/structure/api/item/ItemIdentity;Ljava/lang/String;Ljava/lang/String;[Ljava/lang/Object;)V",
                "method public <init>(Lcom/almworks/jira/structure/api/error/StructureError;)V",
                "method public <init>(Lcom/almworks/jira/structure/api/error/StructureError;Ljava/lang/Long;)V",
                "method public <init>(Lcom/almworks/jira/structure/api/error/StructureError;Ljava/lang/Long;Ljava/lang/Long;)V",
                "method public <init>(Lcom/almworks/jira/structure/api/error/StructureError;Ljava/lang/Long;Ljava/lang/Long;Ljava/lang/Long;)V",
                "method public <init>(Lcom/almworks/jira/structure/api/error/StructureError;Ljava/lang/Long;Ljava/lang/Long;Ljava/lang/Long;Ljava/lang/String;)V",
                "method public <init>(Lcom/almworks/jira/structure/api/error/StructureError;Ljava/lang/Long;Ljava/lang/Long;Ljava/lang/String;)V",
                "method public <init>(Lcom/almworks/jira/structure/api/error/StructureError;Ljava/lang/Long;Ljava/lang/Long;Ljava/lang/String;Ljava/lang/Throwable;)V",
                "method public <init>(Lcom/almworks/jira/structure/api/error/StructureError;Ljava/lang/String;)V",
                "method public asI18nText()Lcom/almworks/jira/structure/api/util/I18nText;",
                "method public getError()Lcom/almworks/jira/structure/api/error/StructureError;",
                "method public getItem()Lcom/almworks/jira/structure/api/item/ItemIdentity;",
                "method public getLocalizedMessage()Ljava/lang/String;",
                "method public getLocalizedMessage(Lcom/atlassian/jira/user/ApplicationUser;)Ljava/lang/String;",
                "method public getProblemDetails()Ljava/lang/String;",
                "method public getRow()J",
                "method public getStructure()J",
                "method public getView()J",
                "method public isLocalized()Z",
                "method public toString()Ljava/lang/String;",
                "type public class");
    }

    @Test
    void structureRow() {
        assertSurface("com.almworks.jira.structure.api.row.StructureRow",
                "field final public static ROW_ZERO:Lcom/almworks/jira/structure/api/row/StructureRow;",
                "method abstract public getItem(Ljava/lang/Class;)Ljava/lang/Object;",
                "method abstract public getItemId()Lcom/almworks/jira/structure/api/item/ItemIdentity;",
                "method abstract public getRowId()J",
                "method abstract public getSemantics()J",
                "type public interface");
    }
}
