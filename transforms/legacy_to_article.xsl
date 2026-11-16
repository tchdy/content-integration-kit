<?xml version="1.0" encoding="UTF-8"?>
<!--
  Maps ONE legacy <doc> to the target <article> model (schemas/article.xsd).
  Called once per record by scripts/migrate.py, so a single bad record fails
  on its own instead of failing the whole batch.

  Shows the common XSLT 1.0 techniques needed for real migrations:
  - code lookups        (state D/R/P -> draft/review/published)
  - string reformatting (dd/mm/yyyy -> yyyy-mm-dd, with substring)
  - splitting a delimited string into repeated elements (recursive template)
  - deriving a URL-safe id from the legacy id (translate + lower-case)
  - omitting optional elements when the source is empty
-->
<xsl:stylesheet version="1.0" xmlns:xsl="http://www.w3.org/1999/XSL/Transform">
  <xsl:output method="xml" encoding="UTF-8" indent="yes"/>

  <xsl:variable name="upper" select="'ABCDEFGHIJKLMNOPQRSTUVWXYZ'"/>
  <xsl:variable name="lower" select="'abcdefghijklmnopqrstuvwxyz'"/>

  <xsl:template match="/doc">
    <article id="{translate(@lid, $upper, $lower)}" legacy-id="{@lid}">
      <xsl:attribute name="status">
        <xsl:choose>
          <xsl:when test="@state = 'P'">published</xsl:when>
          <xsl:when test="@state = 'R'">review</xsl:when>
          <xsl:otherwise>draft</xsl:otherwise>
        </xsl:choose>
      </xsl:attribute>

      <title><xsl:value-of select="normalize-space(hdr/ttl)"/></title>

      <byline>
        <xsl:call-template name="split">
          <xsl:with-param name="text" select="hdr/auth"/>
          <xsl:with-param name="sep" select="';'"/>
          <xsl:with-param name="element" select="'author'"/>
        </xsl:call-template>
      </byline>

      <!-- dd/mm/yyyy -> yyyy-mm-dd; skipped when the legacy date is blank -->
      <xsl:variable name="dt" select="normalize-space(hdr/dt)"/>
      <xsl:if test="string-length($dt) = 10">
        <published>
          <xsl:value-of select="concat(substring($dt, 7, 4), '-', substring($dt, 4, 2), '-', substring($dt, 1, 2))"/>
        </published>
      </xsl:if>

      <!-- No body => no <section>; schema validation then rejects the record. -->
      <xsl:if test="body/p">
        <section>
          <xsl:for-each select="body/p">
            <para><xsl:value-of select="normalize-space(.)"/></para>
          </xsl:for-each>
        </section>
      </xsl:if>

      <xsl:if test="normalize-space(hdr/kw) != ''">
        <tags>
          <xsl:call-template name="split">
            <xsl:with-param name="text" select="hdr/kw"/>
            <xsl:with-param name="sep" select="','"/>
            <xsl:with-param name="element" select="'tag'"/>
          </xsl:call-template>
        </tags>
      </xsl:if>
    </article>
  </xsl:template>

  <!-- Recursive split: XSLT 1.0 has no tokenize(), so peel off one item at a time. -->
  <xsl:template name="split">
    <xsl:param name="text"/>
    <xsl:param name="sep"/>
    <xsl:param name="element"/>
    <xsl:variable name="head" select="normalize-space(substring-before(concat($text, $sep), $sep))"/>
    <xsl:variable name="tail" select="substring-after($text, $sep)"/>
    <xsl:if test="$head != ''">
      <xsl:element name="{$element}"><xsl:value-of select="$head"/></xsl:element>
    </xsl:if>
    <xsl:if test="normalize-space($tail) != ''">
      <xsl:call-template name="split">
        <xsl:with-param name="text" select="$tail"/>
        <xsl:with-param name="sep" select="$sep"/>
        <xsl:with-param name="element" select="$element"/>
      </xsl:call-template>
    </xsl:if>
  </xsl:template>
</xsl:stylesheet>
