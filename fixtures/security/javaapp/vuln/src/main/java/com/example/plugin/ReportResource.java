package com.example.plugin;

import java.io.InputStream;
import java.io.ObjectInputStream;
import java.security.MessageDigest;
import java.sql.Connection;
import java.sql.ResultSet;
import java.sql.Statement;
import javax.servlet.http.HttpServletRequest;
import javax.servlet.http.HttpServletResponse;
import javax.xml.parsers.DocumentBuilder;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Document;

// Planted weaknesses for the Java SAST tests (tests/unit/scorer/test_sec_sast.py). Not a real plugin.
public class ReportResource {
    private final Connection db;

    public ReportResource(Connection db) {
        this.db = db;
    }

    public ResultSet find(HttpServletRequest req) throws Exception {
        String name = req.getParameter("name");
        Statement st = db.createStatement();
        return st.executeQuery("SELECT * FROM report WHERE name = '" + name + "'");
    }

    public void echo(HttpServletRequest req, HttpServletResponse resp) throws Exception {
        resp.getWriter().write("<p>" + req.getParameter("q") + "</p>");
    }

    public Document parse(InputStream in) throws Exception {
        DocumentBuilderFactory f = DocumentBuilderFactory.newInstance();
        DocumentBuilder b = f.newDocumentBuilder();
        return b.parse(in);
    }

    public Object restore(InputStream in) throws Exception {
        return new ObjectInputStream(in).readObject();
    }

    public byte[] token(String s) throws Exception {
        return MessageDigest.getInstance("MD5").digest(s.getBytes());
    }
}
