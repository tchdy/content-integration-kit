<?xml version="1.0" encoding="UTF-8"?>
<!--
  XML-to-XML transform: converts an <article> into an RSS 2.0 <item> for a
  downstream syndication partner. Drafts are filtered out (empty output),
  so only published/review content leaves the system.
-->
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="xml" encoding="UTF-8" indent="yes"/>
  <xsl:param name="base-url" select="'http://localhost:8000'"/>

  <!-- priority="1": both templates match a draft and have equal default priority,
       and an XSLT processor would otherwise pick the last one in the file. -->
  <xsl:template match="/article[@status = 'draft']" priority="1"/>

  <xsl:template match="/article">
    <item>
      <guid isPermaLink="false"><xsl:value-of select="@id"/></guid>
      <title><xsl:value-of select="normalize-space(title)"/></title>
      <link><xsl:value-of select="concat($base-url, '/articles/', @id, '.html')"/></link>
      <author>
        <xsl:for-each select="byline/author">
          <xsl:value-of select="."/>
          <xsl:if test="position() != last()">, </xsl:if>
        </xsl:for-each>
      </author>
      <xsl:if test="published"><pubDate><xsl:value-of select="published"/></pubDate></xsl:if>
      <!-- First paragraph becomes the summary -->
      <description><xsl:value-of select="section[1]/para[1]"/></description>
      <xsl:for-each select="tags/tag"><category><xsl:value-of select="."/></category></xsl:for-each>
    </item>
  </xsl:template>
</xsl:stylesheet>
