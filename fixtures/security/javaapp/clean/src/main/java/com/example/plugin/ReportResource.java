package com.example.plugin;

import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import javax.xml.XMLConstants;
import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Document;

// The clean variant of fixtures/security/javaapp/vuln (tests/unit/scorer/test_sec_sast.py). Not a real plugin.
public class ReportResource {
    private final Connection db;

    public ReportResource(Connection db) {
        this.db = db;
    }

    public ResultSet find(String name) throws Exception {
        PreparedStatement st = db.prepareStatement("SELECT * FROM report WHERE name = ?");
        st.setString(1, name);
        return st.executeQuery();
    }

    public Document parse(InputStream in) throws Exception {
        DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
        f.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
        f.setFeature(XMLConstants.FEATURE_SECURE_PROCESSING, true);
        DocumentBuilder b = f.newDocumentBuilder();
        return b.parse(in);
    }

    public byte[] token(String s) throws Exception {
        return MessageDigest.getInstance("SHA-256").digest(s.getBytes(StandardCharsets.UTF_8));
    }
}
