(function($) {
/*
 * Function: fnGetColumnData
 * Purpose:  Return an array of table values from a particular column.
 * Returns:  array string: 1d data array
 * Inputs:   object:oSettings -
 *             dataTable settings object. This is always the last argument
 *             past to the function
 *           int:iColumn -
 *             the id of the column to extract the data from
 *           function:fnModifier - optional -
 *             the function to modify the data value
 *           bool:bCount - optional -
 *             append the count number to the result data
 *           bool:bUnique - optional -
 *             if set to false duplicated values are not filtered out
 *           bool:bFiltered - optional -
 *             if set to false all the table data is used (not only the
 *             filtered)
 *           bool:bIgnoreEmpty - optional -
 *             if set to false empty values are not filtered from the result
 *             array
 * Author:   Benedikt Forchhammer <b.forchhammer /AT\ mind2.de>
 */
$.fn.dataTableExt.oApi.fnGetColumnData = function (
    oSettings, iColumn, fnModifier, bUnique, bFiltered, bIgnoreEmpty) {

  // check that we have a column id
  if (typeof iColumn == "undefined")
    return new Array();

  // by default we do an identity modifier
  if (typeof fnModifier == "undefined")
    fnModifier = function(sValue) { return sValue; };

  // by default we append count number to the result data
  if (typeof bCount == "undefined")
    bCount = true;

  // by default we only want unique data
  if (typeof bUnique == "undefined")
    bUnique = true;

  // by default we do want to only look at filtered data
  if (typeof bFiltered == "undefined")
    bFiltered = true;

  // by default we do not want to include empty values
  if (typeof bIgnoreEmpty == "undefined")
    bIgnoreEmpty = true;

  // list of rows which we're going to loop through
  var aiRows;

  // use only filtered rows
  if (bFiltered == true)
    aiRows = oSettings.aiDisplay;
  // use all rows
  else
    aiRows = oSettings.aiDisplayMaster; // all row numbers

  // set up data and count array
  var asResultData = new Array();
  var aiResultCount = new Array();

  for (var i = 0, c = aiRows.length; i < c; i++) {
    iRow = aiRows[i];
    var aData = this.fnGetData(iRow);
    var sValue = fnModifier(aData[iColumn]);

    // ignore empty values?
    if (bIgnoreEmpty == true && sValue.length == 0)
      continue;

    // ignore unique values?
    if (bUnique == true && jQuery.inArray(sValue, asResultData) > -1) {
      if (bCount == true)
        aiResultCount[asResultData.indexOf(sValue)]++;
    // else push the value onto the result data array
    } else {
      asResultData.push(sValue);
      if (bCount == true)
        aiResultCount.push(1);
    }
  }

  // append the count to the result data
  if (bCount == true)
    for (var i = 0, c = asResultData.length; i < c; i++)
      asResultData[i] += ' (' + aiResultCount[i].toString() + ')'

  return asResultData;
}}(jQuery));


function fnCreateSelect(aData) {
  var result = '<select><option value=""></option>', i, iLen = aData.length;
  aData = aData.sort()
  for (i = 0; i < iLen; i++) {
    result += '<option value="' + aData[i] + '">' + aData[i] + '</option>';
  }
  return result + '</select>';
}

function fnCutDate(sValue) {
  return sValue.substr(0, 5);
}
