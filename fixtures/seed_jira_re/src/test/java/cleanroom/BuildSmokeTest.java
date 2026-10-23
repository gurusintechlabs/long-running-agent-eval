package cleanroom;

import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.Test;

class BuildSmokeTest {
    @Test
    void theBuildRunsTests() {
        assertTrue(Runtime.version().feature() >= 11);
    }
}
