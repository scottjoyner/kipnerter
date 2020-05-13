package ims.scjoyner.inc.kipnerter.controllers.admin;

import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.RequestMapping;

/**
 * Controller to manage basic abilities for Admin roles
 *
 * @author Kai Presler-Marshall
 *
 */

@Controller
public class AdminController {

    /**
     * Returns the admin for the given model
     *
     * @param model
     *            model to check
     * @return role
     */
    @RequestMapping ( value = "admin/index" )
    @PreAuthorize ( "hasRole('ROLE_ADMIN')" )
    public String index ( final Model model ) {
        return ims.scjoyner.inc.kipnerter.models.enums.Role.ROLE_ADMIN.getLanding();
    }
    
    /**
     * Add or delete user
     *
     * @param model
     *            data for front end
     * @return mapping
     */
    @RequestMapping ( value = "admin/users" )
    @PreAuthorize ( "hasRole('ROLE_ADMIN')" )
    public String manageUser ( final Model model ) {
        return "/admin/users";
    }

    /**
     * Retrieves the form for the Drugs action
     *
     * @param model
     *            Data for front end
     * @return The page to display
     */
    @RequestMapping ( value = "admin/drugs" )
    @PreAuthorize ( "hasRole('ROLE_ADMIN')" )
    public String drugs ( final Model model ) {
        return "admin/drugs";
    }

    /**
     * Returns the page for managing LOINC codes
     *
     * @return the page to display
     */
    @RequestMapping ( value = "admin/manageLOINCCodes" )
    @PreAuthorize ( "hasRole('ROLE_ADMIN')" )
    public String loincCodes () {
        return "/admin/manageLOINCCodes";
    }
    
    /**
     * Creates the form page for the Add Hospital page
     *
     * @param model
     *            Data for the front end
     * @return Page to show to the user
     */
    @RequestMapping ( value = "admin/hospitals" )
    @PreAuthorize ( "hasRole('ROLE_ADMIN')" )
    public String manageHospital ( final Model model ) {
        return "/admin/hospitals";
    }
    
    /**
     * Add code
     *
     * @param model
     *            data for front end
     * @return mapping
     */
    @RequestMapping ( value = "admin/manageICDCodes" )
    @PreAuthorize ( "hasRole('ROLE_ADMIN')" )
    public String addCode ( final Model model ) {
        return "/admin/manageICDCodes";
    }


}
