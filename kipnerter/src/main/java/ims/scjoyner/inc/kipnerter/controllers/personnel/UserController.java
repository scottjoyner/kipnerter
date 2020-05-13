package ims.scjoyner.inc.kipnerter.controllers.personnel;

import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;

import ims.scjoyner.inc.kipnerter.models.enums.TransactionType;
import ims.scjoyner.inc.kipnerter.utils.LoggerUtil;

/**
 * Controller for Personnel to edit their information
 *
 * @author Kai Presler-Marshall
 * @author Scott Joyner
 */
@Controller
public class UserController {

    /**
     * Controller for iTrust2 personnel to modify their demographics.
     * The @PreAuthorize tag will have to be extended if new classes of users
     * are added to the system
     *
     * @param model
     *            information about the vdw
     * @return response
     */
    @GetMapping ( value = "personnel/editDemographics" )
    @PreAuthorize ( "hasAnyRole('ROLE_HCP', 'ROLE_OD', 'ROLE_OPH', 'ROLE_ADMIN', 'ROLE_ER', 'ROLE_LABTECH')" )
    public String viewDemographics ( final Model model ) {
        LoggerUtil.log( TransactionType.VIEW_DEMOGRAPHICS, LoggerUtil.currentUser() );
        return "/personnel/editDemographics";
    }

    /**
     * Returns the image for Dr. Jenkins
     *
     * @return the image for Dr. Jenkins
     */
    @GetMapping ( "/resources/img/wolfpack.jpg" )
    public String viewWolfpack () {
        return "../resources/img/wolfpack.jpg";
    }

}
