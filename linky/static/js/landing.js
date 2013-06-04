var linkyUrl = '';
var rawUrl = '';
var newLinky = {};
var allLinkies = new Array();

$(document).ready(function() {
  $('#linky-confirm').modal({show: false});
  $('#rawUrl').focus();
  
  $('#linker').submit(function() {
		linkIt();
		return false;
	});
	
	$('#email_request').keyup(function() {                   
    if(!$(this).val()) {
      $('#saveLinky').text('Save this Linky');    
    }
    else {
      $('#saveLinky').text('Save and send this Linky');
    }
  });
  
  drawLinks();
});

function linkIt(){
  $('#linky-preview img').attr('src', web_base + '/static/img/infinity_500_400.gif');

  rawUrl = $("#rawUrl").val();
  var request = $.ajax({
    url: web_base + "/api/linky/",
    type: "POST",
    data: {url: rawUrl},
    dataType: "json"
  });
  request.done(function(data) {
    $('#linky_generation_message').html('Your linky has been created at');
    $('#linky-desc').toggleClass('unavailable');
    linkyUrl = web_base  + '/' + data.linky_id;
    newLinky.url = linkyUrl;
    newLinky.original = rawUrl;
    newLinky.title = data.linky_title;
    allLinkies.push(newLinky);
    if(('localStorage' in window) && window['localStorage'] !== null){ 
      localStorage.setItem( 'linky-list', JSON.stringify(allLinkies));
    }
    $('#linkyUrl a').html(web_base  + '/' + data.linky_id).attr('href', web_base + '/' + data.linky_id);
    //$('#linky_title').text(data.linky_title);
    $('#linky-preview img').attr('src', data.linky_url);
  });
  request.fail(function(jqXHR, responseText) {
    //console.log( jqXHR );
  });
  
  $('#linky-confirm').modal('show');
  $('#saveLinky').on('click', function(event){
            
    var request = $.ajax({
      url: web_base + "/service/email-confirm/",
      type: "POST",
      data: {email_address: $('#email_request').val(), linky_link: $('#linkyUrl a').attr('href')},
      dataType: "json"
    });
      
    event.preventDefault();
    $('#linky-confirm').modal('hide');
  });
  
  $('#linky-confirm').on('hidden', function () {
    $('#rawUrl').val('').focus();
    $('#linky-list').fadeIn();
  
    $('#linky_generation_message').html('Creating your Linky. Hold tight.');
    $('#linkyUrl a').html('').attr('');
    $('#linky-desc').toggleClass('unavailable');
    drawLinks();
  });
}

function drawLinks() {
  if(('localStorage' in window) && window['localStorage'] !== null){
    storedLinkies = JSON.parse(localStorage.getItem('linky-list'));
  }
  if(storedLinkies) {
    allLinkies = storedLinkies.reverse();
    $('#linky-list tbody').html('');
    $('#linky-ul').html('');
    $.each( allLinkies, function( key, value ) {
      $('#linky-list tbody').append('<tr><td><a href="' + value.url + '" target="_blank">' + value.url + '</a></td><td><a href="' + value.original + '" target="_blank">' + value.original + '</a></td></tr>');
      $('#linky-ul').append('<li><h4><a href="' + value.url + '" target="_blank">' + value.title + '</a></h4><small>' + value.original + '</small><br><h5><a href="' + value.url + '" target="_blank">' + value.url + '</a></h5></li>');
    });
    $('#linky-list').fadeIn();
  }
}