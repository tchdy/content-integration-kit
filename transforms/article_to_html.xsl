<?xml version="1.0" encoding="UTF-8"?>
<!-- Renders a validated <article> as a standalone HTML page. -->
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="html" encoding="UTF-8" indent="yes"/>

  <xsl:template match="/article">
    <html lang="en">
      <head>
        <meta charset="utf-8"/>
        <title><xsl:value-of select="title"/></title>
        <style>body{font-family:system-ui,sans-serif;max-width:42rem;margin:2rem auto;line-height:1.6;padding:0 1rem}.meta{color:#666}.tag{background:#eef;border-radius:4px;padding:2px 6px;margin-right:4px;font-size:.85em}</style>
      </head>
      <body>
        <article data-id="{@id}" data-status="{@status}">
          <h1><xsl:value-of select="title"/></h1>
          <p class="meta">
            <xsl:text>By </xsl:text>
            <xsl:apply-templates select="byline/author"/>
            <xsl:if test="published">
              <xsl:text> · </xsl:text>
              <time datetime="{published}"><xsl:value-of select="published"/></time>
            </xsl:if>
          </p>
          <xsl:apply-templates select="section"/>
          <xsl:if test="tags/tag">
            <p><xsl:apply-templates select="tags/tag"/></p>
          </xsl:if>
        </article>
      </body>
    </html>
  </xsl:template>

  <!-- "A, B and C" author list -->
  <xsl:template match="author">
    <xsl:value-of select="."/>
    <xsl:choose>
      <xsl:when test="position() = last() - 1"><xsl:text> and </xsl:text></xsl:when>
      <xsl:when test="position() &lt; last()"><xsl:text>, </xsl:text></xsl:when>
    </xsl:choose>
  </xsl:template>

  <xsl:template match="section">
    <section>
      <xsl:if test="heading"><h2><xsl:value-of select="heading"/></h2></xsl:if>
      <xsl:for-each select="para"><p><xsl:value-of select="."/></p></xsl:for-each>
    </section>
  </xsl:template>

  <xsl:template match="tag">
    <span class="tag"><xsl:value-of select="."/></span>
  </xsl:template>
</xsl:stylesheet>
