package cleanroom;

import static org.junit.jupiter.api.Assertions.assertEquals;

import org.junit.jupiter.api.Test;

class BuildSmokeTest {
    @Test
    void theBuildRunsTests() {
        assertEquals(21, Runtime.version().feature());
    }
}
